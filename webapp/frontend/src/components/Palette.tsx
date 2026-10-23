import { useMemo, useState } from "react";
import type { ShapeOut } from "../api";
import { humanLabel } from "../uiLabels";

interface Props {
  shapes: ShapeOut[];
  onCreate: (entityType: string) => void;
}

export const PALETTE_DRAG_MIME = "application/x-drawgen-entity-type";

/** Small library silhouettes, independent of canvas layout and rendering. */
function ShapePreview({ shape }: { shape: string }) {
  const geometry = shape.toLowerCase();
  let silhouette;
  if (geometry.includes("circle")) {
    silhouette = <circle cx="32" cy="22" r="16" />;
  } else if (geometry.includes("diamond")) {
    silhouette = <polygon points="32,4 60,22 32,40 4,22" />;
  } else if (geometry.includes("parallelogram")) {
    silhouette = <polygon points="14,8 60,8 50,36 4,36" />;
  } else if (geometry.includes("hexagon")) {
    silhouette = <polygon points="14,8 50,8 60,22 50,36 14,36 4,22" />;
  } else if (geometry.includes("chevron")) {
    silhouette = <polygon points="4,8 46,8 60,22 46,36 4,36 18,22" />;
  } else if (geometry.includes("cylinder")) {
    silhouette = <><path d="M10 12 A22 7 0 0 1 54 12 V32 A22 7 0 0 1 10 32 Z" /><path d="M10 12 A22 7 0 0 0 54 12" fill="none" /></>;
  } else if (geometry.includes("cloud")) {
    silhouette = <path d="M16 35 C1 35 1 17 15 16 C15 3 35 1 40 13 C55 8 65 28 52 35 Z" />;
  } else if (geometry.includes("wavy bottom")) {
    silhouette = <path d="M8 7 H56 V31 C40 23 25 41 8 33 Z" />;
  } else if (geometry.includes("3d box")) {
    silhouette = <><path d="M8 15 L18 6 H56 V29 L46 38 H8 Z" /><path d="M8 15 H46 V38 M46 15 L56 6" fill="none" /></>;
  } else {
    const rounded = geometry.includes("rounded") ? 6 : /stadium|pill/.test(geometry) ? 14 : 0;
    silhouette = <><rect x="6" y="8" width="52" height="28" rx={rounded} />{ /rows|title band|container/.test(geometry) ? <path d="M6 17 H58" fill="none" /> : null}</>;
  }
  return (
    <svg viewBox="0 0 64 44" width="64" height="44" aria-hidden="true" focusable="false">
      <g fill="#e7e9ed" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round">
        {silhouette}
      </g>
    </svg>
  );
}

export default function Palette({ shapes, onCreate }: Props) {
  const [q, setQ] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const query = q.trim().toLowerCase();

  const families = useMemo(() => {
    const filtered = shapes.filter(
      (s) => !query || [s.entity_type, humanLabel(s.entity_type), s.family, humanLabel(s.family), s.shape]
        .some((text) => text.toLowerCase().includes(query))
    );
    const byFamily = new Map<string, ShapeOut[]>();
    for (const s of filtered) {
      const fam = s.family || "Other";
      if (!byFamily.has(fam)) byFamily.set(fam, []);
      byFamily.get(fam)!.push(s);
    }
    return [...byFamily.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [shapes, query]);

  return (
    <div className="panel palette-panel">
      <h3 className="panel-heading">Shapes</h3>
      <input
        className="search-box"
        type="search"
        aria-label="Search shapes by name, identifier, or category"
        placeholder="Search shapes…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <p className="hint">Drag onto the canvas, or select a shape to add it.</p>
      {families.map(([fam, list]) => (
        <details
          key={fam}
          className="palette-family palette-category"
          open={query ? true : !collapsed.has(fam)}
          onToggle={(e) => {
            if (query) return;
            const open = e.currentTarget.open;
            setCollapsed((previous) => {
              if (previous.has(fam) === !open) return previous;
              const next = new Set(previous);
              if (open) next.delete(fam);
              else next.add(fam);
              return next;
            });
          }}
        >
          <summary className="palette-family-title section-heading" title={fam}>
            {humanLabel(fam)} <span>({list.length})</span>
          </summary>
          <div className="palette-grid">
            {list.map((s) => (
              <button
                type="button"
                key={s.entity_type}
                className="palette-card"
                draggable
                title={s.entity_type}
                aria-label={`Add ${humanLabel(s.entity_type)} (${s.entity_type})`}
                onDragStart={(e) => {
                  e.dataTransfer.setData(PALETTE_DRAG_MIME, s.entity_type);
                  e.dataTransfer.effectAllowed = "copy";
                }}
                onClick={() => onCreate(s.entity_type)}
              >
                <span className="palette-preview"><ShapePreview shape={s.shape} /></span>
                <span className="palette-label">{humanLabel(s.entity_type)}</span>
              </button>
            ))}
          </div>
        </details>
      ))}
      {families.length === 0 && <p className="hint panel-empty" role="status">No shapes match “{q}”.</p>}
    </div>
  );
}
