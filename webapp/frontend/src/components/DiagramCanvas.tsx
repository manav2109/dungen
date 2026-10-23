import { useEffect, useRef, useState, useCallback } from "react";
import type { NodeOut, EdgeOut, ConnectionOut } from "../api";
import type { Tool } from "./Toolbar";
import { PALETTE_DRAG_MIME } from "./Palette";

interface Props {
  svg: string;
  nodes: NodeOut[];
  edges: EdgeOut[];
  connections: Record<string, ConnectionOut[]>;
  selectedNodeIds: string[];
  selectedEdgeId: string | null;
  tool: Tool;
  search: string;
  onSelectNode: (id: string | null, additive?: boolean) => void;
  onSelectEdge: (id: string | null) => void;
  onDragEnd: (nodeId: string, x: number, y: number) => void;
  onConnectCreate: (sourceId: string, targetId: string) => void;
  onDropCreate: (entityType: string, x: number, y: number) => void;
  busy: boolean;
}

/** One connector being previewed while a shape is dragged. */
interface EdgePreview {
  g: SVGGElement;
  path: SVGPathElement;
  d: string;                    // original path, to restore on a non-move
  pts: [number, number][];      // parsed original points
  bothEnds: boolean;            // true when the whole edge moves with the shape
  movesStart: boolean;
  labels: SVGGraphicsElement[];
}

function parsePath(d: string): [number, number][] {
  if (!d.startsWith("M") || /[aAcCqQsStTzZhHvV]/.test(d)) return [];
  const out: [number, number][] = [];
  for (const tok of d.slice(1).replace(/L/g, " ").trim().split(/\s+/)) {
    const [a, b] = tok.split(",");
    const x = Number(a), y = Number(b);
    if (Number.isNaN(x) || Number.isNaN(y)) return [];
    out.push([x, y]);
  }
  return out;
}

/** Edges that should follow `nodeId` — including any attached to its children,
 *  since dragging a container carries everything inside it. */
function collectEdgePreviews(svgEl: SVGSVGElement, nodeId: string): EdgePreview[] {
  const moving = new Set<string>([nodeId]);
  // descendants: walk the rendered groups nested inside this node's group
  const own = svgEl.querySelector(`[data-node-id="${CSS.escape(nodeId)}"]`);
  if (own) {
    own.querySelectorAll("[data-node-id]").forEach((el) => {
      const id = el.getAttribute("data-node-id");
      if (id) moving.add(id);
    });
  }
  const out: EdgePreview[] = [];
  svgEl.querySelectorAll<SVGGElement>("[data-edge-id]").forEach((g) => {
    const src = g.getAttribute("data-source") || "";
    const tgt = g.getAttribute("data-target") || "";
    const a = moving.has(src), b = moving.has(tgt);
    if (!a && !b) return;
    const path = g.querySelector("path");
    if (!path) return;
    const d = path.getAttribute("d") || "";
    const pts = parsePath(d);
    if (pts.length < 2) return;
    out.push({
      g,
      path,
      d,
      pts,
      bothEnds: a && b,
      movesStart: a,
      labels: Array.from(g.querySelectorAll<SVGGraphicsElement>("text, g")),
    });
  });
  return out;
}

/** Redraw the previewed connectors for the current drag offset.
 *
 * This is drag feedback only — a straight rubber-band to the shape's new spot.
 * It deliberately does not try to re-run the engine's routing: that stays the
 * one place routes are computed, and it runs again on drop. */
function applyEdgePreviews(previews: EdgePreview[], dx: number, dy: number) {
  for (const p of previews) {
    if (p.bothEnds) {
      // whole connector travels with the shape — exact, so keep its real shape
      p.g.setAttribute("transform", `translate(${dx},${dy})`);
      continue;
    }
    const pts = p.pts;
    const moved: [number, number] = p.movesStart
      ? [pts[0][0] + dx, pts[0][1] + dy]
      : [pts[pts.length - 1][0] + dx, pts[pts.length - 1][1] + dy];
    const fixed = p.movesStart ? pts[pts.length - 1] : pts[0];
    const [from, to] = p.movesStart ? [moved, fixed] : [fixed, moved];
    p.path.setAttribute("d", `M${from[0].toFixed(0)},${from[1].toFixed(0)} L${to[0].toFixed(0)},${to[1].toFixed(0)}`);
    // the caption's placement is stale the moment an end moves; hide it rather
    // than leave it sitting next to a line that is no longer there
    for (const el of p.labels) el.style.opacity = "0";
  }
}

function restoreEdgePreviews(previews: EdgePreview[]) {
  for (const p of previews) {
    p.g.removeAttribute("transform");
    p.path.setAttribute("d", p.d);
    for (const el of p.labels) el.style.opacity = "";
  }
}

const GRID_STEP = 20;   // world units between grid lines
// The engine happily emits canvases a few thousand pixels wide, so the floor has
// to go low enough that "fit to screen" can actually show one end to end.
const MIN_ZOOM = 0.02;
const MAX_ZOOM = 4;
const FIT_PADDING = 24;

/** Renders the backend-provided SVG string and layers interactivity on top of
 * it (click-to-highlight, drag-to-reposition, connect-tool, palette
 * drag-drop, pan/zoom, search dimming). No layout or routing math lives here
 * — every geometry change is round-tripped through the Python engine so
 * there is exactly one source of truth for where things sit on the canvas. */
export default function DiagramCanvas({
  svg,
  nodes,
  edges,
  connections,
  selectedNodeIds,
  selectedEdgeId,
  tool,
  search,
  onSelectNode,
  onSelectEdge,
  onDragEnd,
  onConnectCreate,
  onDropCreate,
  busy,
}: Props) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const worldRef = useRef<HTMLDivElement>(null);
  const svgElRef = useRef<SVGSVGElement | null>(null);
  const [view, setView] = useState({ x: 0, y: 0, scale: 1 });
  const [connectSource, setConnectSource] = useState<string | null>(null);
  const [showConnections, setShowConnections] = useState(false);
  const dragState = useRef<{
    id: string;
    startClientX: number;
    startClientY: number;
    origX: number;
    origY: number;
    el: SVGGElement;
    shiftKey: boolean;
    edges: EdgePreview[];
    scaleX: number;
    scaleY: number;
  } | null>(null);
  const panState = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(
    null
  );
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null);

  // refs mirroring the latest props, read from inside the SVG-injection
  // effect so that effect doesn't need to re-run (and re-parse the whole SVG
  // string) every time a callback identity or the active tool changes.
  const toolRef = useRef(tool);
  const busyRef = useRef(busy);
  const onSelectNodeRef = useRef(onSelectNode);
  const onSelectEdgeRef = useRef(onSelectEdge);
  const onDragEndRef = useRef(onDragEnd);
  const onConnectCreateRef = useRef(onConnectCreate);
  const nodesRef = useRef(nodes);
  useEffect(() => {
    toolRef.current = tool;
    busyRef.current = busy;
    onSelectNodeRef.current = onSelectNode;
    onSelectEdgeRef.current = onSelectEdge;
    onDragEndRef.current = onDragEnd;
    onConnectCreateRef.current = onConnectCreate;
    nodesRef.current = nodes;
  });

  // connect-tool: clicking a node picks source then target; re-clicking the
  // source cancels; switching tools clears any pending pick.
  useEffect(() => {
    if (tool !== "connect") setConnectSource(null);
  }, [tool]);

  const handleConnectClick = useCallback((id: string) => {
    setConnectSource((cur) => {
      if (!cur) return id;
      if (cur === id) return null;
      onConnectCreateRef.current(cur, id);
      return null;
    });
  }, []);

  const nodeById = useCallback((id: string) => nodes.find((n) => n.id === id), [nodes]);

  // ---------- inject the raw SVG string, then wire up interactivity ----------
  useEffect(() => {
    const world = worldRef.current;
    if (!world) return;
    world.innerHTML = svg;
    const svgEl = world.querySelector("svg") as SVGSVGElement | null;
    svgElRef.current = svgEl;
    if (!svgEl) return;

    const nodeGroups = Array.from(
      svgEl.querySelectorAll<SVGGElement>("[data-node-id]")
    );

    const onPointerDown = (ev: PointerEvent, g: SVGGElement, id: string) => {
      if (busyRef.current) return;
      ev.stopPropagation();
      if (toolRef.current === "connect") {
        handleConnectClick(id);
        return;
      }
      const n = nodesRef.current.find((x) => x.id === id);
      if (!n) return;
      // Measure the screen-to-diagram scale once. Doing it on every pointermove
      // forced a layout of the whole SVG each frame, which is what made dragging
      // a large diagram feel heavy.
      const r0 = svgEl.getBoundingClientRect();
      const vb0 = svgEl.viewBox.baseVal;
      dragState.current = {
        id,
        startClientX: ev.clientX,
        startClientY: ev.clientY,
        origX: n.x,
        origY: n.y,
        el: g,
        shiftKey: ev.shiftKey,
        edges: collectEdgePreviews(svgEl, id),
        scaleX: r0.width ? vb0.width / r0.width : 1,
        scaleY: r0.height ? vb0.height / r0.height : 1,
      };
      window.addEventListener("pointermove", onPointerMove);
      window.addEventListener("pointerup", onPointerUp);
    };

    const onPointerMove = (ev: PointerEvent) => {
      const ds = dragState.current;
      if (!ds) return;
      const dx = (ev.clientX - ds.startClientX) * ds.scaleX;
      const dy = (ev.clientY - ds.startClientY) * ds.scaleY;
      ds.el.setAttribute("transform", `translate(${dx},${dy})`);
      applyEdgePreviews(ds.edges, dx, dy);
    };

    const onPointerUp = (ev: PointerEvent) => {
      const ds = dragState.current;
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      if (!ds) return;
      dragState.current = null;
      const dx = (ev.clientX - ds.startClientX) * ds.scaleX;
      const dy = (ev.clientY - ds.startClientY) * ds.scaleY;
      const moved = Math.abs(dx) > 2 || Math.abs(dy) > 2;
      if (moved) {
        // Deliberately leave the dragged shape and its preview edges where the
        // pointer left them. Snapping them back to the old position here made
        // the drawing jump backwards and sit wrong until the server's re-render
        // arrived, which is what read as lag. The whole SVG is replaced when
        // that response lands, so this preview is discarded then.
        onDragEndRef.current(ds.id, ds.origX + dx, ds.origY + dy);
      } else {
        ds.el.removeAttribute("transform");
        restoreEdgePreviews(ds.edges);
        onSelectNodeRef.current(ds.id, ds.shiftKey);
      }
    };

    for (const g of nodeGroups) {
      const id = g.getAttribute("data-node-id");
      if (!id) continue;
      g.style.cursor = "grab";
      g.addEventListener("pointerdown", (ev) => onPointerDown(ev, g, id));
    }
    svgEl.addEventListener("click", (ev) => {
      const target = ev.target as Element;
      if (target.closest("[data-node-id]")) return; // handled via pointerup above
      const edgeEl = target.closest("[data-edge-id]");
      if (edgeEl) {
        onSelectEdgeRef.current(edgeEl.getAttribute("data-edge-id"));
        return;
      }
      onSelectNodeRef.current(null);
      onSelectEdgeRef.current(null);
    });

    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [svg, handleConnectClick]);

  // ---------- highlight selection / search / connect-pending ----------
  useEffect(() => {
    const svgEl = svgElRef.current;
    if (!svgEl) return;
    const nodeGroups = svgEl.querySelectorAll<SVGGElement>("[data-node-id]");
    const edgeGroups = svgEl.querySelectorAll<SVGGElement>("[data-edge-id]");
    const searchQ = search.trim().toLowerCase();

    let nodeVisible: (id: string) => boolean;
    let edgeVisible: (id: string) => boolean;

    if (selectedEdgeId) {
      const e = edges.find((x) => x.id === selectedEdgeId);
      const related = new Set(e ? [e.source, e.target] : []);
      nodeVisible = (id) => related.has(id);
      edgeVisible = (id) => id === selectedEdgeId;
    } else if (selectedNodeIds.length === 1) {
      const conns = connections[selectedNodeIds[0]] || [];
      const relatedNodeIds = new Set([selectedNodeIds[0], ...conns.map((c) => c.other_id)]);
      const relatedEdgeIds = new Set(conns.map((c) => c.edge_id));
      nodeVisible = (id) => relatedNodeIds.has(id);
      edgeVisible = (id) => relatedEdgeIds.has(id);
    } else if (selectedNodeIds.length > 1) {
      const set = new Set(selectedNodeIds);
      nodeVisible = (id) => set.has(id);
      edgeVisible = (id) => {
        const e = edges.find((x) => x.id === id);
        return !!e && set.has(e.source) && set.has(e.target);
      };
    } else {
      nodeVisible = () => true;
      edgeVisible = () => true;
    }

    nodeGroups.forEach((g) => {
      const id = g.getAttribute("data-node-id")!;
      const n = nodeById(id);
      const matchesSearch = !searchQ || (n?.label.toLowerCase().includes(searchQ) ?? false);
      g.style.opacity = matchesSearch && nodeVisible(id) ? "1" : "0.15";
      g.classList.toggle("connect-source", id === connectSource);
    });
    edgeGroups.forEach((g) => {
      const id = g.getAttribute("data-edge-id")!;
      g.style.opacity = edgeVisible(id) ? "1" : "0.12";
    });
  }, [selectedNodeIds, selectedEdgeId, connections, svg, search, edges, connectSource, nodeById]);

  // ---------- bring a newly selected node into view if it's off-screen ----------
  useEffect(() => {
    const svgEl = svgElRef.current;
    const viewport = viewportRef.current;
    const soleId = selectedNodeIds.length === 1 ? selectedNodeIds[0] : null;
    if (!svgEl || !viewport || !soleId) return;
    const n = nodeById(soleId);
    const nodeEl = svgEl.querySelector<SVGGElement>(`[data-node-id="${CSS.escape(soleId)}"]`);
    if (!n || !nodeEl) return;
    const vpRect = viewport.getBoundingClientRect();
    const nodeRect = nodeEl.getBoundingClientRect();
    const margin = 48;
    const visible =
      nodeRect.left >= vpRect.left + margin &&
      nodeRect.right <= vpRect.right - margin &&
      nodeRect.top >= vpRect.top + margin &&
      nodeRect.bottom <= vpRect.bottom - margin;
    if (visible) return;
    const cx = n.x + n.w / 2;
    const cy = n.y + n.h / 2;
    setView((v) => ({
      ...v,
      x: vpRect.width / 2 - v.scale * cx,
      y: vpRect.height / 2 - v.scale * cy,
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedNodeIds]);

  // ---------- track the selected node's screen position for the tooltip ----------
  useEffect(() => {
    const svgEl = svgElRef.current;
    const viewport = viewportRef.current;
    const soleId = !selectedEdgeId && selectedNodeIds.length === 1 ? selectedNodeIds[0] : null;
    if (!svgEl || !viewport || !soleId) {
      setTooltipPos(null);
      return;
    }
    const computePos = () => {
      const nodeEl = svgEl.querySelector<SVGGElement>(`[data-node-id="${CSS.escape(soleId)}"]`);
      if (!nodeEl) {
        setTooltipPos(null);
        return;
      }
      const vpRect = viewport.getBoundingClientRect();
      const nodeRect = nodeEl.getBoundingClientRect();
      setTooltipPos({
        x: nodeRect.left - vpRect.left + nodeRect.width / 2,
        y: nodeRect.top - vpRect.top,
      });
    };
    computePos();
    window.addEventListener("resize", computePos);
    return () => window.removeEventListener("resize", computePos);
  }, [selectedNodeIds, selectedEdgeId, view, svg]);

  // ---------- pan / zoom ----------
  // The world is `translate(x, y) scale(s)` with origin 0 0, so a world point p
  // sits at screen `xy + s*p`. Zooming therefore has to move `xy` as well, or the
  // drawing slides out from under whatever the user was looking at.
  const zoomAt = (factor: number, cx: number, cy: number) =>
    setView((v) => {
      const scale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.scale * factor));
      if (scale === v.scale) return v;
      // keep the world point currently under (cx, cy) pinned there
      return {
        scale,
        x: cx - (scale / v.scale) * (cx - v.x),
        y: cy - (scale / v.scale) * (cy - v.y),
      };
    });

  // Wheel is attached natively rather than via React's onWheel: React registers
  // wheel listeners passively, so preventDefault() there is ignored (and logs a
  // console warning) — which let the page itself scroll instead of the canvas.
  useEffect(() => {
    const vp = viewportRef.current;
    if (!vp) return;
    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault();
      const rect = vp.getBoundingClientRect();
      // Ctrl/Cmd + wheel is the zoom convention; a trackpad pinch also arrives
      // as a wheel event with ctrlKey set, so both gestures land here.
      if (ev.ctrlKey || ev.metaKey) {
        zoomAt(Math.exp(-ev.deltaY * 0.002), ev.clientX - rect.left, ev.clientY - rect.top);
        return;
      }
      // Otherwise scroll the canvas. Shift+wheel scrolls horizontally (the usual
      // shortcut for mice with only a vertical wheel); trackpads send deltaX
      // directly, so honour both.
      const dx = ev.shiftKey ? ev.deltaY : ev.deltaX;
      const dy = ev.shiftKey ? 0 : ev.deltaY;
      setView((v) => ({ ...v, x: v.x - dx, y: v.y - dy }));
    };
    vp.addEventListener("wheel", onWheel, { passive: false });
    return () => vp.removeEventListener("wheel", onWheel);
  }, []);

  const startPan = (clientX: number, clientY: number) => {
    panState.current = { startX: clientX, startY: clientY, origX: view.x, origY: view.y };
    const onMove = (mv: PointerEvent) => {
      const ps = panState.current;
      if (!ps) return;
      setView((v) => ({ ...v, x: ps.origX + (mv.clientX - ps.startX), y: ps.origY + (mv.clientY - ps.startY) }));
    };
    const onUp = () => {
      panState.current = null;
      document.body.classList.remove("panning");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const onBgPointerDown = (ev: React.PointerEvent) => {
    // Middle-drag pans from anywhere, including from on top of a shape — the
    // other standard way to move around a canvas this size.
    if (ev.button === 1) {
      ev.preventDefault();
      document.body.classList.add("panning");
      startPan(ev.clientX, ev.clientY);
      return;
    }
    if (ev.button !== 0) return;
    if ((ev.target as Element).closest("[data-node-id]")) return;
    startPan(ev.clientX, ev.clientY);
  };

  // Measurements the view commands share: viewport box plus the drawing's own
  // size in world units. Returns null before the SVG has been injected.
  const measure = () => {
    const vp = viewportRef.current;
    const el = svgElRef.current;
    if (!vp || !el) return null;
    const sw = el.viewBox.baseVal?.width || el.width.baseVal.value;
    const sh = el.viewBox.baseVal?.height || el.height.baseVal.value;
    if (!sw || !sh) return null;
    return { vw: vp.clientWidth, vh: vp.clientHeight, sw, sh };
  };

  /** Scale the drawing down (or up) until the whole thing is on screen. */
  const fitToScreen = () => {
    const m = measure();
    if (!m) return setView({ x: 0, y: 0, scale: 1 });
    const scale = Math.min(
      MAX_ZOOM,
      Math.max(MIN_ZOOM, Math.min((m.vw - FIT_PADDING * 2) / m.sw, (m.vh - FIT_PADDING * 2) / m.sh))
    );
    setView({ scale, x: (m.vw - m.sw * scale) / 2, y: (m.vh - m.sh * scale) / 2 });
  };

  /** Re-centre the drawing without touching the current zoom level. */
  const center = () => {
    const m = measure();
    if (!m) return;
    setView((v) => ({ ...v, x: (m.vw - m.sw * v.scale) / 2, y: (m.vh - m.sh * v.scale) / 2 }));
  };

  /** Back to 1:1 — the "actual size" command.
   *
   * Centred while the drawing fits, but anchored to its top-left corner once it
   * is larger than the viewport: centring an over-wide diagram pushes both
   * edges off screen at once and opens you in the middle of it, with no way to
   * tell which direction the start is in. */
  const resetZoom = () => {
    const m = measure();
    if (!m) return setView({ x: 0, y: 0, scale: 1 });
    setView({
      scale: 1,
      x: m.sw <= m.vw ? (m.vw - m.sw) / 2 : FIT_PADDING,
      y: m.sh <= m.vh ? (m.vh - m.sh) / 2 : FIT_PADDING,
    });
  };

  const zoomBy = (f: number) => {
    const vp = viewportRef.current;
    // Anchor the button zoom on the middle of the viewport, so repeated clicks
    // magnify what's on screen instead of walking towards the top-left corner.
    const cx = vp ? vp.clientWidth / 2 : 0;
    const cy = vp ? vp.clientHeight / 2 : 0;
    zoomAt(f, cx, cy);
  };

  // Open at actual size, centred. Shapes and type are sized in real pixels by
  // the engine, so 1:1 is the only zoom at which what you see matches what gets
  // exported — auto-fitting used to open a wide diagram at ~60%, where the
  // labels the engine had carefully spaced were too small to read. A diagram
  // too big for the viewport is centred on its middle rather than pinned to a
  // corner, and Fit is one click away. This fires once per mount, and App
  // remounts the canvas (via a key on the diagram id) when a different diagram
  // loads, so an edit never yanks the view.
  const didFit = useRef(false);
  useEffect(() => {
    if (didFit.current || !svgElRef.current) return;
    didFit.current = true;
    resetZoom();
  }, [svg]);

  // ---------- drop a palette shape onto the canvas ----------
  const onDragOver = (ev: React.DragEvent) => {
    if (ev.dataTransfer.types.includes(PALETTE_DRAG_MIME)) {
      ev.preventDefault();
      ev.dataTransfer.dropEffect = "copy";
    }
  };
  const onDrop = (ev: React.DragEvent) => {
    const entityType = ev.dataTransfer.getData(PALETTE_DRAG_MIME);
    if (!entityType) return;
    ev.preventDefault();
    const svgNode = svgElRef.current;
    if (!svgNode) return;
    const rect = svgNode.getBoundingClientRect();
    const vb = svgNode.viewBox.baseVal;
    const scaleX = vb.width / rect.width;
    const scaleY = vb.height / rect.height;
    const x = vb.x + (ev.clientX - rect.left) * scaleX;
    const y = vb.y + (ev.clientY - rect.top) * scaleY;
    onDropCreate(entityType, x, y);
  };

  const selectedSoleId = !selectedEdgeId && selectedNodeIds.length === 1 ? selectedNodeIds[0] : null;

  // Grid drawn on the viewport itself rather than on the diagram, so it fills
  // the whole area and keeps going wherever you pan — the drawing then reads as
  // sitting on an endless surface instead of stopping at the edge of its page.
  // Offsetting the pattern by the pan and scaling it by the zoom makes it move
  // with the content, which is what sells the effect.
  const gridSize = GRID_STEP * view.scale;
  const gridStyle: React.CSSProperties =
    gridSize >= 6
      ? {
          backgroundImage:
            "linear-gradient(to right, var(--grid-line) 1px, transparent 1px)," +
            "linear-gradient(to bottom, var(--grid-line) 1px, transparent 1px)",
          backgroundSize: `${gridSize}px ${gridSize}px`,
          // keep the pattern anchored to the world origin as it pans
          backgroundPosition: `${view.x}px ${view.y}px`,
        }
      : {}; // zoomed too far out — a grid this dense is just noise

  return (
    <div
      className="diagram-viewport"
      ref={viewportRef}
      style={gridStyle}
      onPointerDown={onBgPointerDown}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      {tool === "connect" && (
        <div className="canvas-hint">
          {connectSource
            ? "Click the target shape (or click the source again to cancel)"
            : "Click a source shape to start a connection"}
        </div>
      )}
      <div className="zoom-controls" role="group" aria-label="Canvas view controls" onPointerDown={(event) => event.stopPropagation()}>
        {selectedSoleId && <button className="zoom-wide" aria-pressed={showConnections} onClick={() => setShowConnections((show) => !show)} title="Show or hide the selected shape's connections">Connections</button>}
        <button onClick={() => zoomBy(1.2)} title="Zoom in" aria-label="Zoom in">+</button>
        <button
          className="zoom-readout"
          onClick={resetZoom}
          title="Actual size (100%)"
          aria-label={`Zoom ${Math.round(view.scale * 100)} percent — click for actual size`}
        >
          {Math.round(view.scale * 100)}%
        </button>
        <button onClick={() => zoomBy(1 / 1.2)} title="Zoom out" aria-label="Zoom out">−</button>
        <button className="zoom-wide" onClick={fitToScreen} title="Fit the whole diagram on screen">
          Fit
        </button>
        <button className="zoom-wide" onClick={center} title="Centre the diagram at the current zoom">
          Center
        </button>
      </div>
      {busy && <div className="canvas-busy" role="status">Updating diagram…</div>}
      <div
        className="diagram-world"
        ref={worldRef}
        style={{
          transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
          transformOrigin: "0 0",
        }}
      />
      {showConnections && selectedSoleId && tooltipPos && (
        <div
          className="node-tooltip"
          style={{ left: tooltipPos.x, top: tooltipPos.y }}
          onPointerDown={(ev) => ev.stopPropagation()}
        >
          <div className="node-tooltip-title">{nodeById(selectedSoleId)?.label ?? selectedSoleId}</div>
          <ul className="node-tooltip-links">
            {(connections[selectedSoleId] || []).map((c) => (
              <li key={c.edge_id}>
                <a
                  href="#"
                  onClick={(ev) => {
                    ev.preventDefault();
                    onSelectNode(c.other_id);
                  }}
                >
                  <span className={`dir dir-${c.dir}`}>{c.dir === "out" ? "→" : "←"}</span>
                  {c.other_label}
                </a>
              </li>
            ))}
            {(connections[selectedSoleId] || []).length === 0 && (
              <li className="hint">No connections.</li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
