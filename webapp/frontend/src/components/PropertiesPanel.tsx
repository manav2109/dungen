import { useState } from "react";
import type { ConnectionOut, EdgeOut, LineOut, NodeOut, ShapeOut } from "../api";
import { humanLabel } from "../uiLabels";

interface Props {
  nodes: NodeOut[];
  edges: EdgeOut[];
  shapes: ShapeOut[];
  lines: LineOut[];
  connections: Record<string, ConnectionOut[]>;
  selectedNodeIds: string[];
  selectedEdgeId: string | null;
  onSelectNode: (id: string | null) => void;
  onUpdateNode: (nodeId: string, patch: { label?: string; entity_type?: string; fill_override?: string; stroke_override?: string; metadata?: string }) => void;
  onDeleteNode: (nodeId: string) => void;
  onDuplicateNode: (nodeId: string) => void;
  onReparentNode: (nodeId: string, parent: string) => void;
  onBulkDeleteNodes: (nodeIds: string[]) => void;
  onUpdateEdge: (edgeId: string, patch: { relation_type?: string; label?: string; reverse?: boolean }) => void;
  onDeleteEdge: (edgeId: string) => void;
}

/** Refresh server values immediately unless this field has an unsaved edit. */
function useDraftField(owner: string | undefined, source: string) {
  const [draft, setDraft] = useState({ owner, source, value: source, dirty: false });
  let current = draft;
  if (draft.owner !== owner || draft.source !== source) {
    const keepEdit = draft.owner === owner && draft.dirty;
    current = { owner, source, value: keepEdit ? draft.value : source, dirty: keepEdit && draft.value !== source };
    setDraft(current);
  }
  return {
    value: current.value,
    change: (value: string) => setDraft({ owner, source, value, dirty: value !== source }),
    commit: (save: (value: string) => void) => {
      if (current.dirty && current.value !== source) save(current.value);
      // The server response clears dirtiness when it confirms this value.
      // Keep a failed edit retryable rather than marking it saved on dispatch.
    },
    reset: (value: string) => setDraft({ owner, source, value, dirty: false }),
  };
}

function hexColor(value: string): string | null {
  if (/^#[\da-f]{6}$/i.test(value)) return value;
  if (/^#[\da-f]{3}$/i.test(value)) return `#${value.slice(1).split("").map((digit) => digit + digit).join("")}`;
  return null;
}

export default function PropertiesPanel({
  nodes,
  edges,
  shapes,
  lines,
  connections,
  selectedNodeIds,
  selectedEdgeId,
  onSelectNode,
  onUpdateNode,
  onDeleteNode,
  onDuplicateNode,
  onReparentNode,
  onBulkDeleteNodes,
  onUpdateEdge,
  onDeleteEdge,
}: Props) {
  const edge = selectedEdgeId ? edges.find((e) => e.id === selectedEdgeId) : null;
  const node = !edge && selectedNodeIds.length === 1 ? nodes.find((n) => n.id === selectedNodeIds[0]) : null;

  const label = useDraftField(node?.id, node?.label || "");
  const fill = useDraftField(node?.id, node?.fill_override || "");
  const stroke = useDraftField(node?.id, node?.stroke_override || "");
  const meta = useDraftField(node?.id, node?.metadata || "");
  const edgeLabel = useDraftField(edge?.id, edge?.label || "");

  if (edge) {
    return (
      <div className="panel">
        <h3 className="panel-heading">Connection</h3>
        <section className="panel-section" aria-label="Basic">
          <h4 className="section-heading">Basic</h4>
          <label className="field">
            <span>Connection type</span>
            <select
              value={edge.relation}
              onChange={(e) => onUpdateEdge(edge.id, { relation_type: e.target.value })}
            >
              {!lines.some((l) => l.relation_type === edge.relation) && <option value={edge.relation}>{humanLabel(edge.relation)}</option>}
              {lines.map((l) => (
                <option key={l.relation_type} value={l.relation_type}>
                  {humanLabel(l.relation_type)}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Label</span>
            <input
              value={edgeLabel.value}
              onChange={(e) => edgeLabel.change(e.target.value)}
              onBlur={() => edgeLabel.commit((value) => onUpdateEdge(edge.id, { label: value }))}
            />
          </label>
          <p className="hint">Type ID: <code>{edge.relation}</code></p>
        </section>
        <section className="panel-section" aria-label="Connections">
          <h4 className="section-heading">Connections</h4>
          <p className="hint">
            {nodes.find((n) => n.id === edge.source)?.label ?? edge.source} → {nodes.find((n) => n.id === edge.target)?.label ?? edge.target}
          </p>
          <div className="btn-row">
            <button type="button" className="btn" onClick={() => onUpdateEdge(edge.id, { reverse: true })}>
              Reverse direction
            </button>
          </div>
        </section>
        <button type="button" className="link-btn" onClick={() => onSelectNode(null)}>
          Clear selection
        </button>
        <footer className="panel-footer">
          <button type="button" className="btn btn-danger" onClick={() => onDeleteEdge(edge.id)}>Delete connection</button>
        </footer>
      </div>
    );
  }

  if (selectedNodeIds.length > 1) {
    return (
      <div className="panel">
        <h3 className="panel-heading">{selectedNodeIds.length} shapes selected</h3>
        <button type="button" className="link-btn" onClick={() => onSelectNode(null)}>
          Clear selection
        </button>
        <footer className="panel-footer">
          <button type="button" className="btn btn-danger" onClick={() => onBulkDeleteNodes(selectedNodeIds)}>
            Delete selected shapes
          </button>
        </footer>
      </div>
    );
  }

  if (!node) {
    return (
      <div className="panel">
        <h3 className="panel-heading">Properties</h3>
        <p className="hint panel-empty">Select a shape or connection to edit its properties.</p>
      </div>
    );
  }

  const conns = connections[node.id] || [];
  const shape = shapes.find((s) => s.entity_type === node.type);
  const fillColor = fill.value || shape?.fill || "";
  const strokeColor = stroke.value || shape?.stroke || "";

  return (
    <div className="panel">
      <h3 className="panel-heading">{node.label || humanLabel(node.type)}</h3>
      <section className="panel-section" aria-label="Basic">
        <h4 className="section-heading">Basic</h4>
        <label className="field">
          <span>Label</span>
          <input value={label.value} onChange={(e) => label.change(e.target.value)} onBlur={() => label.commit((value) => onUpdateNode(node.id, { label: value }))} />
        </label>
        <label className="field">
          <span>Shape type</span>
          <select value={node.type} onChange={(e) => onUpdateNode(node.id, { entity_type: e.target.value })}>
            {!shape && <option value={node.type}>{humanLabel(node.type)}</option>}
            {shapes.map((s) => (
              <option key={s.entity_type} value={s.entity_type}>
                {humanLabel(s.entity_type)}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Parent container</span>
          <select value={node.parent || ""} onChange={(e) => onReparentNode(node.id, e.target.value)}>
            <option value="">None (top level)</option>
            {nodes
              .filter((n) => n.id !== node.id)
              .map((n) => (
                <option key={n.id} value={n.id}>
                  {n.label}
                </option>
              ))}
          </select>
        </label>
        <p className="hint">Type ID: <code>{node.type}</code></p>
        <button type="button" className="btn" onClick={() => onDuplicateNode(node.id)}>Duplicate shape</button>
      </section>
      <section className="panel-section" aria-label="Appearance">
        <h4 className="section-heading">Appearance</h4>
        <div className="field-row">
          <label className="field">
            <span>Fill color</span>
            {fillColor && !hexColor(fillColor) ? <svg width="44" height="28" aria-hidden="true" focusable="false"><rect x="1" y="1" width="42" height="26" rx="5" fill={fillColor} stroke="currentColor" /></svg> : null}
            <input
              type={hexColor(fillColor) ? "color" : "text"}
              value={hexColor(fillColor) || fillColor}
              placeholder="Color"
              onChange={(e) => fill.change(e.target.value)}
              onBlur={() => fill.commit((value) => onUpdateNode(node.id, { fill_override: value }))}
            />
            <small className="hint">{fill.value ? "Override" : "Shape default"}{fillColor ? ` · ${fillColor}` : " unavailable"}</small>
          </label>
          <label className="field">
            <span>Border color</span>
            {strokeColor && !hexColor(strokeColor) ? <svg width="44" height="28" aria-hidden="true" focusable="false"><rect x="1" y="1" width="42" height="26" rx="5" fill={strokeColor} stroke="currentColor" /></svg> : null}
            <input
              type={hexColor(strokeColor) ? "color" : "text"}
              value={hexColor(strokeColor) || strokeColor}
              placeholder="Color"
              onChange={(e) => stroke.change(e.target.value)}
              onBlur={() => stroke.commit((value) => onUpdateNode(node.id, { stroke_override: value }))}
            />
            <small className="hint">{stroke.value ? "Override" : "Shape default"}{strokeColor ? ` · ${strokeColor}` : " unavailable"}</small>
          </label>
        </div>
        <button type="button" className="link-btn" disabled={!fill.value && !stroke.value && !node.fill_override && !node.stroke_override} onPointerDown={(event) => {
          // A pointer reset must not submit the draft first via input blur.
          // Keyboard Tab still commits edits normally, even if Reset is next.
          event.preventDefault();
        }} onClick={() => {
          fill.reset("");
          stroke.reset("");
          onUpdateNode(node.id, { fill_override: "", stroke_override: "" });
        }}>Reset to shape defaults</button>
        <p className="hint">Style rules may change the colors shown on the canvas.</p>
      </section>
      <section className="panel-section" aria-label="Connections">
        <h4 className="section-heading">Connections ({conns.length})</h4>
        <ul className="conn-list">
          {conns.map((c) => (
            <li key={c.edge_id}>
              <button type="button" className="connection-button" onClick={() => onSelectNode(c.other_id)} aria-label={`Select ${c.other_label}: ${c.dir === "out" ? "outgoing" : "incoming"} connection${c.label ? `, ${c.label}` : ""}`}>
                <span className={`dir dir-${c.dir}`} aria-hidden="true">{c.dir === "out" ? "→" : "←"}</span>
                <span className="conn-other">{c.other_label}</span>
                {c.label && <span className="conn-label">{c.label}</span>}
              </button>
            </li>
          ))}
          {conns.length === 0 && <li className="hint">No connections.</li>}
        </ul>
      </section>
      <details key={node.id} className="advanced-settings panel-section">
        <summary className="section-heading">Advanced</summary>
        <label className="field">
          <span>Metadata</span>
          <textarea rows={3} value={meta.value} onChange={(e) => meta.change(e.target.value)} onBlur={() => meta.commit((value) => onUpdateNode(node.id, { metadata: value }))} aria-describedby="shape-metadata-help" />
        </label>
        <p id="shape-metadata-help" className="hint">Use key=value pairs separated by semicolons.</p>
      </details>
      <footer className="panel-footer">
        <button type="button" className="btn btn-danger" onClick={() => onDeleteNode(node.id)}>Delete shape</button>
      </footer>
    </div>
  );
}
