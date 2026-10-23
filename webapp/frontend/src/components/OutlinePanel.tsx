import { useState } from "react";
import type { LineOut, ShapeOut } from "../api";
import { humanLabel } from "../uiLabels";

interface Props {
  shapes: ShapeOut[];
  lines: LineOut[];
  onGenerate: (text: string, entityType: string, relationType: string) => void;
}

const DEFAULT_TEXT = `Vision\n  Strategy A\n    Initiative 1\n    Initiative 2\n  Strategy B\n    Initiative 3`;

export default function OutlinePanel({ shapes, lines, onGenerate }: Props) {
  const [text, setText] = useState(DEFAULT_TEXT);
  const [entityType, setEntityType] = useState("business_actor");
  const [relationType, setRelationType] = useState("association");

  return (
    <div className="panel">
      <p className="hint">
        Indented outline (2 spaces or a tab per level) becomes a node tree — each line under a shallower
        line gets a parent-child connection.
      </p>
      <label className="field">
        <span>Outline text</span>
        <textarea rows={10} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
      </label>
      <label className="field">
        <span>Node type</span>
        <select value={entityType} onChange={(e) => setEntityType(e.target.value)}>
          {shapes.map((s) => (
            <option key={s.entity_type} value={s.entity_type}>
              {humanLabel(s.entity_type)}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Connection type</span>
        <select value={relationType} onChange={(e) => setRelationType(e.target.value)}>
          {lines.map((l) => (
            <option key={l.relation_type} value={l.relation_type}>
              {humanLabel(l.relation_type)}
            </option>
          ))}
        </select>
      </label>
      <button className="btn btn-primary" onClick={() => onGenerate(text, entityType, relationType)}>
        Generate diagram
      </button>
    </div>
  );
}
