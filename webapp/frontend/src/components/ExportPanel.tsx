import { useCallback, useEffect, useMemo, useState } from "react";
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

interface StoredSettings {
  clusters?: Record<string, Omit<ClusterForm, "id">>;
  orphanAssignments?: Record<string, string>;
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

  const persistSettings = useCallback(() => {
    const settings = {
      ...diagram.export_settings,
      pptx: {
        clusters: Object.fromEntries(
          Object.values(clusterForms).map(({ id, ...rest }) => [id, rest])
        ),
        orphanAssignments,
      },
    };
    saveExportSettings(diagram.session_id, settings).catch(() => {});
    // Optimistic: the save above is fire-and-forget (closing the panel
    // shouldn't block on it), so update the parent's copy immediately
    // rather than waiting on a response this component may not be
    // mounted to receive.
    onSettingsSaved(settings);
  }, [diagram.export_settings, diagram.session_id, clusterForms, orphanAssignments, onSettingsSaved]);

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
          return { slide_number: slideNumber, placements };
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
  }, [detect, clusterForms, orphansByCluster, diagram.svg, diagram.title, diagram.session_id, projectName, persistSettings, onClose]);

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
                  <svg className="pptx-slide-preview" viewBox={`0 0 ${SLIDE_W} ${SLIDE_H}`} aria-hidden="true">
                    <rect x={0} y={0} width={SLIDE_W} height={SLIDE_H} className="pptx-slide-rect" />
                    <rect x={form.x} y={form.y} width={form.w} height={form.h} className="pptx-placement-rect" />
                  </svg>
                )}
              </div>
            );
          })}

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
