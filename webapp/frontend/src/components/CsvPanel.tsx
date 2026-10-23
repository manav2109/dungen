import { useState } from "react";
import type { LineOut, ShapeOut } from "../api";

interface Props {
  unknownTypes: string[];
  shapes: ShapeOut[];
  lines: LineOut[];
  onApply: (nodesCsv: string, edgesCsv: string, shapesCsv: string, linesCsv: string) => void;
}

const NODES_HEADER =
  "node_id,parent_id,entity_type,label,rank_hint,order_hint,fill_override,stroke_override,metadata";
const EDGES_HEADER = "edge_id,source_id,target_id,relation_type,label";

export default function CsvPanel({ unknownTypes, shapes, lines, onApply }: Props) {
  const exampleEntityType = shapes[0]?.entity_type ?? "entity_type";
  const exampleRelationType = lines[0]?.relation_type ?? "relation_type";
  const [nodesCsv, setNodesCsv] = useState(
    `${NODES_HEADER}\nn1,,${exampleEntityType},Example node,,,,,\n`
  );
  const [edgesCsv, setEdgesCsv] = useState(`${EDGES_HEADER}\ne1,n1,n1,${exampleRelationType},\n`);
  const [showRules, setShowRules] = useState(false);
  const [shapesCsv, setShapesCsv] = useState("");
  const [linesCsv, setLinesCsv] = useState("");

  return (
    <div className="panel data-panel">
      <div className="panel-heading"><h3>Edit diagram data</h3></div>
      <p className="hint">
        Paste Nodes/Edges CSV (same headers as the workbook) and apply it to the active diagram. Unknown
        entity/relation types are skipped and reported below. Prefilled with one example row per box —
        edit or replace it.
      </p>
      <label className="field">
        <span>Nodes CSV</span>
        <textarea rows={8} value={nodesCsv} onChange={(e) => setNodesCsv(e.target.value)} spellCheck={false} />
      </label>
      {shapes.length > 0 && (
        <details className="syntax-help"><summary>Supported shape types</summary><p className="hint">
          Valid entity_type values: {shapes.map((s) => s.entity_type).join(", ")}
        </p></details>
      )}
      <label className="field">
        <span>Edges CSV</span>
        <textarea rows={5} value={edgesCsv} onChange={(e) => setEdgesCsv(e.target.value)} spellCheck={false} />
      </label>
      {lines.length > 0 && (
        <details className="syntax-help"><summary>Supported connection types</summary><p className="hint">
          Valid relation_type values: {lines.map((l) => l.relation_type).join(", ")}
        </p></details>
      )}
      <button className="link-btn" onClick={() => setShowRules((v) => !v)}>
        {showRules ? "Hide" : "Add"} custom Shape_Library / Line_Rules rows
      </button>
      {showRules && (
        <>
          <label className="field">
            <span>Shape_Library CSV</span>
            <textarea rows={4} value={shapesCsv} onChange={(e) => setShapesCsv(e.target.value)} spellCheck={false} />
          </label>
          <label className="field">
            <span>Line_Rules CSV</span>
            <textarea rows={4} value={linesCsv} onChange={(e) => setLinesCsv(e.target.value)} spellCheck={false} />
          </label>
        </>
      )}
      <button className="btn btn-primary" onClick={() => onApply(nodesCsv, edgesCsv, shapesCsv, linesCsv)}>
        Apply CSV to canvas
      </button>
      {unknownTypes.length > 0 && (
        <p className="warn">Skipped unknown types: {unknownTypes.join(", ")}</p>
      )}
    </div>
  );
}
