import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Modal, Tabs, Button, Select, InputNumber, Input, Checkbox, Spin, Empty, Segmented, Collapse } from "antd";
import type { ClusterOut, ClusterDetectResponse, DiagramResponse, OrphanOut } from "../api";
import { detectPptxClusters, exportPptx, saveExportSettings } from "../api";
import { padBBox, rasterizeSvgRegion, unionBBox, type BBox } from "../svgRaster";

type Preset = "full" | "top-half" | "bottom-half" | "centered";
// "shapes": each box becomes a real, individually-editable PowerPoint
// shape (and real connectors) — see diagen/pptx_shapes.py. "picture": the
// original flat raster crop, an exact visual copy that can't be edited.
type DisplayMode = "shapes" | "picture";

interface ClusterForm {
  id: string;
  name: string;
  included: boolean;
  slideNumber: number;
  preset: Preset;
  mode: DisplayMode;
  // Which of this cluster's top-level member/assigned-orphan node ids to
  // leave OUT of the export — stored as an exclusion list (not inclusion)
  // so a newly-assigned orphan is included by default without this form
  // needing to know about it in advance.
  excludedNodeIds: string[];
  x: number;
  y: number;
  w: number;
  h: number;
}

// Widescreen 16:9, in inches — PowerPoint's current default.
const SLIDE_W = 13.333;
const SLIDE_H = 7.5;
const MARGIN = 0.4;
const RASTER_PADDING = 24; // SVG units of breathing room around a crop, so a shape's own stroke never gets clipped flush at the edge.

function fitBox(targetX: number, targetY: number, targetW: number, targetH: number, aspect: number) {
  let w = targetW;
  let h = w / aspect;
  if (h > targetH) {
    h = targetH;
    w = h * aspect;
  }
  return { x: targetX + (targetW - w) / 2, y: targetY + (targetH - h) / 2, w, h };
}

function applyPreset(preset: Preset, bbox: BBox): { x: number; y: number; w: number; h: number } {
  const aspect = bbox.w / Math.max(1, bbox.h);
  switch (preset) {
    case "top-half":
      return fitBox(MARGIN, MARGIN, SLIDE_W - 2 * MARGIN, SLIDE_H / 2 - 1.5 * MARGIN, aspect);
    case "bottom-half":
      return fitBox(MARGIN, SLIDE_H / 2 + 0.5 * MARGIN, SLIDE_W - 2 * MARGIN, SLIDE_H / 2 - 1.5 * MARGIN, aspect);
    case "centered": {
      const w = SLIDE_W - 2 * MARGIN;
      const h = w / aspect;
      return { x: MARGIN, y: Math.max(MARGIN, (SLIDE_H - h) / 2), w, h };
    }
    case "full":
    default:
      return fitBox(MARGIN, MARGIN, SLIDE_W - 2 * MARGIN, SLIDE_H - 2 * MARGIN, aspect);
  }
}

function defaultClusterForm(cluster: ClusterOut, index: number): ClusterForm {
  const box = applyPreset("full", cluster.bbox);
  return {
    id: cluster.id,
    name: cluster.suggested_name,
    included: true,
    slideNumber: index + 1,
    preset: "full",
    mode: "shapes",
    excludedNodeIds: [],
    ...box,
  };
}

type TextBlockKind = "header" | "content";

interface TextBlockForm {
  text: string;
  font: string;
  size: number;
  // Content only — prefixes each non-blank line with "• " at send time, a
  // plain-text approximation rather than real PPTX bullet XML, enough to
  // get bullet-style notes without new backend plumbing.
  bullets: boolean;
  x: number;
  y: number;
  w: number;
  h: number;
}

interface SlideTextForm {
  header?: TextBlockForm | null;
  content?: TextBlockForm | null;
}

const TEXT_FONT_OPTIONS = ["Calibri", "Arial", "Georgia", "Verdana", "Times New Roman"].map((f) => ({
  value: f,
  label: f,
}));

function defaultTextBlock(kind: TextBlockKind): TextBlockForm {
  return kind === "header"
    ? { text: "", font: "Calibri", size: 28, bullets: false, x: MARGIN, y: 0.15, w: SLIDE_W - 2 * MARGIN, h: 0.9 }
    : { text: "", font: "Calibri", size: 16, bullets: false, x: MARGIN, y: SLIDE_H - 1.3, w: SLIDE_W - 2 * MARGIN, h: 1.1 };
}

function escapeXml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function overviewOverlayRect(bbox: BBox, label: string, kind: string): string {
  const pad = 8;
  const x = bbox.x - pad;
  const y = bbox.y - pad;
  const w = bbox.w + pad * 2;
  const h = bbox.h + pad * 2;
  return (
    `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="6" class="pptx-overview-rect pptx-overview-${kind}" />` +
    `<text x="${x + 6}" y="${y - 8}" class="pptx-overview-label pptx-overview-${kind}">${escapeXml(label)}</text>`
  );
}

/** Splices cluster/orphan highlight rects directly into a copy of the
 * diagram's own rendered SVG, instead of a plain list — `render_svg.py`'s
 * root `viewBox` already uses the same coordinate units as `bbox` on every
 * cluster/orphan, so the overlay lines up with zero conversion math. Labels
 * are untrusted node/cluster text, so they're XML-escaped before splicing
 * into markup that gets rendered via dangerouslySetInnerHTML. */
function buildDiagramOverviewSvg(
  svgMarkup: string,
  clusters: ClusterOut[],
  clusterNames: Record<string, string>,
  orphans: OrphanOut[],
  orphanAssignments: Record<string, string>
): string {
  const openTagEnd = svgMarkup.indexOf(">");
  const closeTagStart = svgMarkup.lastIndexOf("</svg>");
  if (openTagEnd < 0 || closeTagStart < 0) return svgMarkup;
  const openTag = svgMarkup
    .slice(0, openTagEnd + 1)
    .replace(/\swidth="[^"]*"/, "")
    .replace(/\sheight="[^"]*"/, "")
    .replace("<svg", '<svg width="100%"');
  const inner = svgMarkup.slice(openTagEnd + 1, closeTagStart);

  const overlays =
    clusters.map((c) => overviewOverlayRect(c.bbox, clusterNames[c.id] || c.suggested_name, "cluster")).join("") +
    orphans
      .map((o) => {
        const assigned = orphanAssignments[o.node_id];
        const excluded = !assigned || assigned === "exclude";
        const label = excluded ? `${o.label} (excluded)` : `${o.label} → ${clusterNames[assigned] || assigned}`;
        return overviewOverlayRect(o.bbox, label, excluded ? "orphan-excluded" : "orphan-assigned");
      })
      .join("");

  return `${openTag}${inner}<g class="pptx-overview-overlay">${overlays}</g></svg>`;
}

/** A slide-sized SVG preview whose placement rect can be dragged to
 * reposition it — the x/y fields in "Fine-tune position" are the numeric
 * escape hatch, this is the primary way most people will actually move a
 * placement. Pointer capture keeps the drag going even if the cursor
 * leaves the rect mid-move. */
function PptxSlidePreview({
  form,
  onMove,
}: {
  form: Pick<ClusterForm, "x" | "y" | "w" | "h">;
  onMove: (x: number, y: number) => void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<{ startClientX: number; startClientY: number; startX: number; startY: number } | null>(null);

  const onPointerDown = (e: React.PointerEvent<SVGRectElement>) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = { startClientX: e.clientX, startClientY: e.clientY, startX: form.x, startY: form.y };
  };
  // Shared by move and up: some input methods (a synthetic/instant drag,
  // a trackpad that coalesces events) can deliver a pointerdown and a
  // pointerup with no pointermove in between — committing only on move
  // would silently lose the drag, so up re-applies the same math from
  // whatever its own final coordinates are.
  const applyFromEvent = (e: React.PointerEvent<SVGRectElement>) => {
    if (!dragRef.current || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    const scaleX = SLIDE_W / rect.width;
    const scaleY = SLIDE_H / rect.height;
    const dx = (e.clientX - dragRef.current.startClientX) * scaleX;
    const dy = (e.clientY - dragRef.current.startClientY) * scaleY;
    const maxX = Math.max(0, SLIDE_W - form.w);
    const maxY = Math.max(0, SLIDE_H - form.h);
    const x = Math.min(Math.max(0, dragRef.current.startX + dx), maxX);
    const y = Math.min(Math.max(0, dragRef.current.startY + dy), maxY);
    onMove(x, y);
  };
  const onPointerUp = (e: React.PointerEvent<SVGRectElement>) => {
    if (!dragRef.current) return;
    applyFromEvent(e);
    e.currentTarget.releasePointerCapture(e.pointerId);
    dragRef.current = null;
  };

  return (
    <svg ref={svgRef} className="pptx-slide-preview" viewBox={`0 0 ${SLIDE_W} ${SLIDE_H}`} aria-hidden="true">
      <rect x={0} y={0} width={SLIDE_W} height={SLIDE_H} className="pptx-slide-rect" />
      <rect
        x={form.x}
        y={form.y}
        width={form.w}
        height={form.h}
        className="pptx-placement-rect pptx-placement-draggable"
        onPointerDown={onPointerDown}
        onPointerMove={applyFromEvent}
        onPointerUp={onPointerUp}
      />
    </svg>
  );
}

interface StoredSettings {
  clusters?: Record<string, Omit<ClusterForm, "id">>;
  orphanAssignments?: Record<string, string>;
  slideTexts?: Record<number, SlideTextForm>;
}

export default function ExportPanel({
  diagram,
  projectName,
  onClose,
  onDownloadSimple,
  onSettingsSaved,
}: {
  diagram: DiagramResponse;
  // The name the user actually gave their *saved project* (App.tsx's
  // currentProjectName) — not diagram.title, which is a separate, looser
  // field (defaults to "Untitled diagram" and isn't what Save/Save-as
  // writes). Empty until the first save, so falls back to diagram.title.
  projectName: string;
  onClose: () => void;
  onDownloadSimple: (kind: "svg" | "drawio" | "html") => void;
  // Settings are saved server-side via saveExportSettings, but this panel
  // remounts from scratch each time it opens (App.tsx conditionally
  // mounts it) and seeds its state from `diagram.export_settings` — a
  // snapshot frozen at whatever the last DiagramResponse fetch returned.
  // Saving doesn't refresh that prop on its own, so without this callback
  // reopening the panel in the same session would show stale settings
  // even though the server has the latest.
  onSettingsSaved: (settings: Record<string, unknown>) => void;
}) {
  const [tab, setTab] = useState<"html" | "svg" | "drawio" | "pptx">("pptx");
  const [detect, setDetect] = useState<ClusterDetectResponse | null>(null);
  const [detectError, setDetectError] = useState<string | null>(null);
  const [clusterForms, setClusterForms] = useState<Record<string, ClusterForm>>({});
  // node_id -> cluster id, or "exclude"
  const [orphanAssignments, setOrphanAssignments] = useState<Record<string, string>>({});
  // slide number -> optional title/caption text blocks for that slide.
  const [slideTexts, setSlideTexts] = useState<Record<number, SlideTextForm>>({});
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    detectPptxClusters(diagram.session_id)
      .then((result) => {
        if (cancelled) return;
        setDetect(result);
        const stored = (diagram.export_settings?.pptx as StoredSettings | undefined) || {};
        const forms: Record<string, ClusterForm> = {};
        result.clusters.forEach((cluster, index) => {
          const saved = stored.clusters?.[cluster.id];
          // Merge onto fresh defaults rather than replacing wholesale —
          // settings saved before "mode"/"excludedNodeIds" existed would
          // otherwise load with those fields undefined.
          forms[cluster.id] = { ...defaultClusterForm(cluster, index), ...saved, id: cluster.id };
        });
        setClusterForms(forms);
        const assignments: Record<string, string> = {};
        result.orphans.forEach((orphan) => {
          const saved = stored.orphanAssignments?.[orphan.node_id];
          if (saved) {
            assignments[orphan.node_id] = saved;
          } else if (orphan.confident && orphan.suggested_cluster_id) {
            assignments[orphan.node_id] = orphan.suggested_cluster_id;
          } else {
            assignments[orphan.node_id] = "exclude";
          }
        });
        setOrphanAssignments(assignments);
        setSlideTexts(stored.slideTexts || {});
      })
      .catch(() => !cancelled && setDetectError("Could not analyze this diagram for export."));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [diagram.session_id]);

  const updateCluster = useCallback((id: string, patch: Partial<ClusterForm>) => {
    setClusterForms((cur) => ({ ...cur, [id]: { ...cur[id], ...patch } }));
  }, []);

  const onPresetChange = useCallback(
    (id: string, preset: Preset, bbox: BBox) => {
      updateCluster(id, { preset, ...applyPreset(preset, bbox) });
    },
    [updateCluster]
  );

  const toggleTextBlock = useCallback((slideNumber: number, kind: TextBlockKind, on: boolean) => {
    setSlideTexts((cur) => ({
      ...cur,
      [slideNumber]: { ...cur[slideNumber], [kind]: on ? cur[slideNumber]?.[kind] || defaultTextBlock(kind) : null },
    }));
  }, []);

  const updateTextBlock = useCallback(
    (slideNumber: number, kind: TextBlockKind, patch: Partial<TextBlockForm>) => {
      setSlideTexts((cur) => {
        const existing = cur[slideNumber]?.[kind];
        if (!existing) return cur;
        return { ...cur, [slideNumber]: { ...cur[slideNumber], [kind]: { ...existing, ...patch } } };
      });
    },
    []
  );

  const persistSettings = useCallback(() => {
    const settings = {
      ...diagram.export_settings,
      pptx: {
        clusters: Object.fromEntries(
          Object.values(clusterForms).map(({ id, ...rest }) => [id, rest])
        ),
        orphanAssignments,
        slideTexts,
      },
    };
    saveExportSettings(diagram.session_id, settings).catch(() => {});
    // Optimistic: the save above is fire-and-forget (closing the panel
    // shouldn't block on it), so update the parent's copy immediately
    // rather than waiting on a response this component may not be
    // mounted to receive.
    onSettingsSaved(settings);
  }, [diagram.export_settings, diagram.session_id, clusterForms, orphanAssignments, slideTexts, onSettingsSaved]);

  const nodesById = useMemo(
    () => Object.fromEntries(diagram.nodes.map((n) => [n.id, n])),
    [diagram.nodes]
  );

  const orphansByCluster = useMemo(() => {
    const map: Record<string, OrphanOut[]> = {};
    (detect?.orphans || []).forEach((o) => {
      const target = orphanAssignments[o.node_id];
      if (!target || target === "exclude") return;
      (map[target] ||= []).push(o);
    });
    return map;
  }, [detect, orphanAssignments]);

  const overviewSvg = useMemo(() => {
    if (!detect || (detect.clusters.length === 0 && detect.orphans.length === 0)) return null;
    const clusterNames = Object.fromEntries(Object.values(clusterForms).map((f) => [f.id, f.name]));
    return buildDiagramOverviewSvg(diagram.svg, detect.clusters, clusterNames, detect.orphans, orphanAssignments);
  }, [detect, clusterForms, orphanAssignments, diagram.svg]);

  // Only slides that actually have an included diagram on them — a slide
  // can't be generated with text alone (the backend requires at least one
  // placement per slide), so there's nothing useful to show text
  // controls for otherwise.
  const slideNumbers = useMemo(() => {
    const set = new Set<number>();
    Object.values(clusterForms).forEach((f) => {
      if (f.included) set.add(f.slideNumber);
    });
    return Array.from(set).sort((a, b) => a - b);
  }, [clusterForms]);

  const onGenerate = useCallback(async () => {
    if (!detect) return;
    setGenerating(true);
    setGenError(null);
    try {
      type Pending =
        | { form: ClusterForm; kind: "picture"; crop: BBox }
        | { form: ClusterForm; kind: "shapes"; nodeIds: string[] };
      const bySlide: Record<number, Pending[]> = {};
      for (const cluster of detect.clusters) {
        const form = clusterForms[cluster.id];
        if (!form?.included) continue;
        const assignedOrphans = orphansByCluster[cluster.id] || [];
        if (form.mode === "picture") {
          const crop = padBBox(
            unionBBox([cluster.bbox, ...assignedOrphans.map((o) => o.bbox)]),
            RASTER_PADDING
          );
          (bySlide[form.slideNumber] ||= []).push({ form, kind: "picture", crop });
        } else {
          const memberIds = [...cluster.top_level_ids, ...assignedOrphans.map((o) => o.node_id)];
          const nodeIds = memberIds.filter((id) => !form.excludedNodeIds.includes(id));
          if (nodeIds.length === 0) continue;
          (bySlide[form.slideNumber] ||= []).push({ form, kind: "shapes", nodeIds });
        }
      }
      const slideNumbers = Object.keys(bySlide).map(Number);
      if (slideNumbers.length === 0) {
        setGenError("Nothing is included — enable at least one diagram.");
        return;
      }
      const toTextPayload = (block: TextBlockForm | null | undefined) => {
        if (!block || !block.text.trim()) return undefined;
        const text = block.bullets
          ? block.text
              .split("\n")
              .map((line) => line.trim())
              .filter(Boolean)
              .map((line) => `• ${line}`)
              .join("\n")
          : block.text;
        return { text, font: block.font, size: block.size, x: block.x, y: block.y, w: block.w, h: block.h };
      };
      const slides = await Promise.all(
        slideNumbers.map(async (slideNumber) => {
          const placements = await Promise.all(
            bySlide[slideNumber].map(async (pending) => {
              const { form } = pending;
              if (pending.kind === "shapes") {
                return { node_ids: pending.nodeIds, x: form.x, y: form.y, w: form.w, h: form.h };
              }
              return {
                image_png_base64: await rasterizeSvgRegion(diagram.svg, pending.crop),
                x: form.x,
                y: form.y,
                w: form.w,
                h: form.h,
              };
            })
          );
          const text = slideTexts[slideNumber];
          return {
            slide_number: slideNumber,
            placements,
            header: toTextPayload(text?.header),
            content: toTextPayload(text?.content),
          };
        })
      );
      await exportPptx({
        session_id: diagram.session_id,
        filename: projectName || diagram.title || "diagram",
        slide_width_in: SLIDE_W,
        slide_height_in: SLIDE_H,
        slides,
      });
      persistSettings();
      onClose();
    } catch (e: any) {
      setGenError(e?.message || "Could not generate the PPTX file.");
    } finally {
      setGenerating(false);
    }
  }, [detect, clusterForms, orphansByCluster, slideTexts, diagram.svg, diagram.title, diagram.session_id, projectName, persistSettings, onClose]);

  return (
    <Modal
      open
      onCancel={() => {
        persistSettings();
        onClose();
      }}
      title="Export diagram"
      width={760}
      footer={null}
      destroyOnHidden
    >
      <Tabs
        activeKey={tab}
        onChange={(k) => setTab(k as typeof tab)}
        items={[
          { key: "html", label: "HTML" },
          { key: "svg", label: "SVG" },
          { key: "drawio", label: "draw.io" },
          { key: "pptx", label: "PowerPoint" },
        ]}
      />

      {tab !== "pptx" && (
        <div className="export-simple-tab">
          <p className="hint">
            {tab === "html" && "A standalone web page with this diagram, ready to open in any browser."}
            {tab === "svg" && "A vector image — scales to any size without losing quality."}
            {tab === "drawio" && "An editable diagram.net / draw.io file."}
          </p>
          <Button
            type="primary"
            onClick={() => {
              onDownloadSimple(tab);
              onClose();
            }}
          >
            Download {tab === "drawio" ? "draw.io" : tab.toUpperCase()}
          </Button>
        </div>
      )}

      {tab === "pptx" && (
        <div className="export-pptx-tab">
          {!detect && !detectError && (
            <div className="export-pptx-loading">
              <Spin /> Looking for separate diagrams on this canvas…
            </div>
          )}
          {detectError && <p className="error">{detectError}</p>}
          {detect && detect.clusters.length === 0 && (
            <Empty description="No connected shapes found to export." />
          )}

          {overviewSvg && (
            <div className="pptx-overview-section">
              <p className="eyebrow">What's on this canvas</p>
              <p className="hint">
                Each highlighted group becomes its own diagram below. Amber boxes are shapes not
                connected to anything — assign or exclude them further down.
              </p>
              <div className="pptx-overview-wrap" dangerouslySetInnerHTML={{ __html: overviewSvg }} />
            </div>
          )}

          {detect?.clusters.map((cluster) => {
            const form = clusterForms[cluster.id];
            if (!form) return null;
            const assigned = orphansByCluster[cluster.id] || [];
            return (
              <div key={cluster.id} className="pptx-cluster-row">
                <div className="pptx-cluster-head">
                  <Checkbox
                    checked={form.included}
                    onChange={(e) => updateCluster(cluster.id, { included: e.target.checked })}
                  />
                  <Input
                    value={form.name}
                    onChange={(e) => updateCluster(cluster.id, { name: e.target.value })}
                    style={{ width: 220 }}
                  />
                  <span className="pptx-cluster-meta">
                    {cluster.top_level_ids.length} shape{cluster.top_level_ids.length === 1 ? "" : "s"}
                    {assigned.length > 0 && ` + ${assigned.length} orphan${assigned.length === 1 ? "" : "s"}`}
                  </span>
                </div>
                {form.included && (
                  <div className="pptx-mode-row">
                    <Segmented
                      value={form.mode}
                      onChange={(mode) => updateCluster(cluster.id, { mode: mode as DisplayMode })}
                      options={[
                        { value: "shapes", label: "Native shapes" },
                        { value: "picture", label: "Picture" },
                      ]}
                    />
                    <p className="hint pptx-mode-hint">
                      {form.mode === "shapes"
                        ? "Each box stays its own editable PowerPoint shape — you can move, recolor, or delete pieces afterward. Connecting lines may route a little differently than shown here."
                        : "An exact visual copy of what's on screen, embedded as one flat image — can't be edited or taken apart in PowerPoint."}
                    </p>
                  </div>
                )}
                {form.included && form.mode === "shapes" && (
                  <div className="pptx-node-checklist">
                    <p className="eyebrow">Shapes to include on this slide</p>
                    {cluster.top_level_ids.map((nodeId) => (
                      <label key={nodeId} className="pptx-node-check">
                        <Checkbox
                          checked={!form.excludedNodeIds.includes(nodeId)}
                          onChange={(e) =>
                            updateCluster(cluster.id, {
                              excludedNodeIds: e.target.checked
                                ? form.excludedNodeIds.filter((id) => id !== nodeId)
                                : [...form.excludedNodeIds, nodeId],
                            })
                          }
                        />
                        {nodesById[nodeId]?.label || nodeId}
                      </label>
                    ))}
                    {assigned.map((orphan) => (
                      <label key={orphan.node_id} className="pptx-node-check">
                        <Checkbox
                          checked={!form.excludedNodeIds.includes(orphan.node_id)}
                          onChange={(e) =>
                            updateCluster(cluster.id, {
                              excludedNodeIds: e.target.checked
                                ? form.excludedNodeIds.filter((id) => id !== orphan.node_id)
                                : [...form.excludedNodeIds, orphan.node_id],
                            })
                          }
                        />
                        {orphan.label} <span className="pptx-orphan-tag">orphan</span>
                      </label>
                    ))}
                  </div>
                )}
                {form.included && (
                  <div className="pptx-cluster-fields">
                    <label>
                      Slide
                      <InputNumber
                        min={1}
                        max={500}
                        value={form.slideNumber}
                        onChange={(v) => updateCluster(cluster.id, { slideNumber: v || 1 })}
                      />
                    </label>
                    <label>
                      Layout
                      <Select
                        value={form.preset}
                        style={{ width: 160 }}
                        onChange={(preset: Preset) => onPresetChange(cluster.id, preset, cluster.bbox)}
                        options={[
                          { value: "full", label: "Full slide" },
                          { value: "top-half", label: "Top half" },
                          { value: "bottom-half", label: "Bottom half" },
                          { value: "centered", label: "Centered, fit width" },
                        ]}
                      />
                    </label>
                  </div>
                )}
                {form.included && (
                  <Collapse
                    ghost
                    size="small"
                    className="pptx-finetune-collapse"
                    items={[
                      {
                        key: "finetune",
                        label: "Fine-tune position",
                        children: (
                          <div className="pptx-cluster-fields">
                            <p className="hint">Measured in inches from the slide's top-left corner.</p>
                            <label>
                              Horizontal position (in)
                              <InputNumber
                                min={0}
                                max={SLIDE_W}
                                step={0.1}
                                value={form.x}
                                onChange={(v) => updateCluster(cluster.id, { x: v ?? form.x })}
                              />
                            </label>
                            <label>
                              Vertical position (in)
                              <InputNumber
                                min={0}
                                max={SLIDE_H}
                                step={0.1}
                                value={form.y}
                                onChange={(v) => updateCluster(cluster.id, { y: v ?? form.y })}
                              />
                            </label>
                            <label>
                              Width (in)
                              <InputNumber
                                min={0.5}
                                max={SLIDE_W}
                                step={0.1}
                                value={form.w}
                                onChange={(v) => updateCluster(cluster.id, { w: v ?? form.w })}
                              />
                            </label>
                            <label>
                              Height (in)
                              <InputNumber
                                min={0.5}
                                max={SLIDE_H}
                                step={0.1}
                                value={form.h}
                                onChange={(v) => updateCluster(cluster.id, { h: v ?? form.h })}
                              />
                            </label>
                          </div>
                        ),
                      },
                    ]}
                  />
                )}
                {form.included && (
                  <PptxSlidePreview form={form} onMove={(x, y) => updateCluster(cluster.id, { x, y })} />
                )}
              </div>
            );
          })}

          {slideNumbers.length > 0 && (
            <div className="pptx-slide-texts">
              <p className="eyebrow">Slide text</p>
              <p className="hint">
                Optional title and caption text for each slide — rendered as real PowerPoint text
                boxes, separate from the diagram itself.
              </p>
              {slideNumbers.map((slideNumber) => (
                <div key={slideNumber} className="pptx-slide-text-row">
                  <p className="pptx-slide-text-heading">Slide {slideNumber}</p>
                  {(["header", "content"] as const).map((kind) => {
                    const block = slideTexts[slideNumber]?.[kind];
                    return (
                      <div key={kind} className="pptx-textblock">
                        <Checkbox
                          checked={!!block}
                          onChange={(e) => toggleTextBlock(slideNumber, kind, e.target.checked)}
                        >
                          {kind === "header" ? "Title text" : "Caption / notes text"}
                        </Checkbox>
                        {block && (
                          <>
                            <Input.TextArea
                              value={block.text}
                              onChange={(e) => updateTextBlock(slideNumber, kind, { text: e.target.value })}
                              placeholder={
                                kind === "header" ? "Slide title" : "One line per paragraph or bullet"
                              }
                              autoSize={{ minRows: kind === "header" ? 1 : 2, maxRows: 6 }}
                            />
                            <div className="pptx-textblock-fields">
                              <label>
                                Font
                                <Select
                                  value={block.font}
                                  style={{ width: 160 }}
                                  options={TEXT_FONT_OPTIONS}
                                  onChange={(font) => updateTextBlock(slideNumber, kind, { font })}
                                />
                              </label>
                              <label>
                                Size (pt)
                                <InputNumber
                                  min={6}
                                  max={96}
                                  value={block.size}
                                  onChange={(v) => updateTextBlock(slideNumber, kind, { size: v ?? block.size })}
                                />
                              </label>
                              {kind === "content" && (
                                <label className="pptx-bullets-toggle">
                                  <Checkbox
                                    checked={block.bullets}
                                    onChange={(e) =>
                                      updateTextBlock(slideNumber, kind, { bullets: e.target.checked })
                                    }
                                  />
                                  Bullet points
                                </label>
                              )}
                            </div>
                            <Collapse
                              ghost
                              size="small"
                              className="pptx-finetune-collapse"
                              items={[
                                {
                                  key: "finetune",
                                  label: "Fine-tune position",
                                  children: (
                                    <div className="pptx-cluster-fields">
                                      <p className="hint">Measured in inches from the slide's top-left corner.</p>
                                      <label>
                                        Horizontal position (in)
                                        <InputNumber
                                          min={0}
                                          max={SLIDE_W}
                                          step={0.1}
                                          value={block.x}
                                          onChange={(v) => updateTextBlock(slideNumber, kind, { x: v ?? block.x })}
                                        />
                                      </label>
                                      <label>
                                        Vertical position (in)
                                        <InputNumber
                                          min={0}
                                          max={SLIDE_H}
                                          step={0.1}
                                          value={block.y}
                                          onChange={(v) => updateTextBlock(slideNumber, kind, { y: v ?? block.y })}
                                        />
                                      </label>
                                      <label>
                                        Width (in)
                                        <InputNumber
                                          min={0.5}
                                          max={SLIDE_W}
                                          step={0.1}
                                          value={block.w}
                                          onChange={(v) => updateTextBlock(slideNumber, kind, { w: v ?? block.w })}
                                        />
                                      </label>
                                      <label>
                                        Height (in)
                                        <InputNumber
                                          min={0.3}
                                          max={SLIDE_H}
                                          step={0.1}
                                          value={block.h}
                                          onChange={(v) => updateTextBlock(slideNumber, kind, { h: v ?? block.h })}
                                        />
                                      </label>
                                    </div>
                                  ),
                                },
                              ]}
                            />
                          </>
                        )}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          )}

          {detect && detect.orphans.length > 0 && (
            <div className="pptx-orphans">
              <p className="eyebrow">
                Shapes not connected to a diagram ({detect.orphans.length})
              </p>
              <p className="hint">
                These aren't linked to anything by a line, so we can't tell which diagram they
                belong to on their own. Pick one, or leave a shape out of the export entirely —
                its position never changes, only which slide it shows up on.
              </p>
              {detect.orphans.map((orphan) => (
                <div key={orphan.node_id} className="pptx-orphan-row">
                  <span className={`pptx-orphan-badge ${orphanAssignments[orphan.node_id] === "exclude" ? "excluded" : ""}`}>
                    {orphan.label}
                  </span>
                  {!orphan.confident && <span className="pptx-orphan-flag">needs a pick</span>}
                  <Select
                    value={orphanAssignments[orphan.node_id] || "exclude"}
                    style={{ width: 220 }}
                    onChange={(v) => setOrphanAssignments((cur) => ({ ...cur, [orphan.node_id]: v }))}
                    options={[
                      { value: "exclude", label: "Leave out of export" },
                      ...detect.clusters.map((c) => ({
                        value: c.id,
                        label: clusterForms[c.id]?.name || c.suggested_name,
                      })),
                    ]}
                  />
                </div>
              ))}
            </div>
          )}

          {genError && <p className="error">{genError}</p>}
          <div className="pptx-actions">
            <Button onClick={() => { persistSettings(); onClose(); }}>Cancel</Button>
            <Button type="primary" loading={generating} disabled={!detect} onClick={onGenerate}>
              Generate PPTX
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
