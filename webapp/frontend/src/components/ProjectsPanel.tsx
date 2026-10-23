import { useEffect, useState } from "react";
import type { ProjectInfo } from "../api";

interface Props {
  projects: ProjectInfo[];
  currentProjectId: string | null;
  currentName: string;
  busy: boolean;
  onSave: (name: string) => void;
  onSaveAsCopy: (name: string) => void;
  onLoad: (id: string, name: string) => void;
  onDelete: (id: string) => void;
}

function timeAgo(unixSeconds: number): string {
  const mins = Math.max(0, Math.floor((Date.now() - unixSeconds * 1000) / 60000));
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins} minute${mins === 1 ? "" : "s"} ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return new Date(unixSeconds * 1000).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function ProjectsPanel({
  projects,
  currentProjectId,
  currentName,
  busy,
  onSave,
  onSaveAsCopy,
  onLoad,
  onDelete,
}: Props) {
  const [name, setName] = useState(currentName);

  useEffect(() => {
    setName(currentName);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentProjectId]);

  return (
    <div className="panel">
      <p className="hint">
        Save your diagram to pick up where you left off. Each project includes all
        sub-diagrams, your palette, and style rules.
      </p>
      <label className="field">
        <span>Name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Untitled" />
      </label>
      <button
        type="button"
        className="btn btn-primary"
        disabled={busy || !name.trim()}
        onClick={() => onSave(name.trim())}
      >
        {currentProjectId ? "Save" : "Save as new"}
      </button>
      {currentProjectId && (
        <button type="button" className="btn" disabled={busy || !name.trim()} onClick={() => onSaveAsCopy(name.trim())}>
          Save as a copy
        </button>
      )}

      <h3 className="section-heading" style={{ marginTop: 16 }}>
        Saved projects
      </h3>
      {projects.length === 0 && <p className="hint">Your saved projects will appear here. Give this diagram a name to save it.</p>}
      <ul className="project-list">
        {projects.map((p) => (
          <li key={p.id} className={p.id === currentProjectId ? "active" : ""}>
            <button
              type="button"
              className="btn project-row-main"
              aria-label={`Open project ${p.name}`}
              aria-current={p.id === currentProjectId ? "true" : undefined}
              onClick={() => onLoad(p.id, p.name)}
            >
              <span className="project-name">{p.name}</span>
              <time
                className="project-time"
                dateTime={new Date(p.updated_at * 1000).toISOString()}
                title={`Updated ${new Date(p.updated_at * 1000).toLocaleString()}`}
              >
                {timeAgo(p.updated_at)}
              </time>
            </button>
            <button
              type="button"
              className="btn btn-danger project-delete"
              title={`Delete ${p.name}`}
              aria-label={`Delete project ${p.name}`}
              onClick={() => {
                if (window.confirm(`Delete "${p.name}"? This can't be undone.`)) onDelete(p.id);
              }}
            >
              ✕
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
