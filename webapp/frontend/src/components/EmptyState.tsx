import { useEffect, useId, useRef, useState } from "react";
import type { LineOut, ProjectInfo, SampleInfo, ShapeOut } from "../api";
import { downloadSample, getPalette, listSamples, sampleLabel, sampleMeta } from "../api";
import TemplatesPanel from "./TemplatesPanel";
import OutlinePanel from "./OutlinePanel";

interface Props {
  onBlank: () => void;
  onSample: (name: string) => void;
  onUpload: (file: File) => void;
  onGenerateTemplate: (templateName: string, params: Record<string, string>) => void;
  onGenerateOutline: (text: string, entityType: string, relationType: string) => void;
  projects?: ProjectInfo[];
  onLoadProject?: (id: string, name: string) => void;
}

type Expanded = "template" | "outline" | null;

export default function EmptyState({
  onBlank,
  onSample,
  onUpload,
  onGenerateTemplate,
  onGenerateOutline,
  projects,
  onLoadProject,
}: Props) {
  const [samples, setSamples] = useState<SampleInfo[]>([]);
  const [expanded, setExpanded] = useState<Expanded>(null);
  const [shapes, setShapes] = useState<ShapeOut[]>([]);
  const [lines, setLines] = useState<LineOut[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  const sectionId = useId();
  const recentProjects = onLoadProject
    ? [...(projects ?? [])].sort((a, b) => b.updated_at - a.updated_at).slice(0, 4)
    : [];

  useEffect(() => {
    listSamples().then(setSamples).catch(() => setSamples([]));
    getPalette()
      .then((p) => {
        setShapes(p.shapes);
        setLines(p.lines);
      })
      .catch(() => {});
  }, []);

  const toggle = (which: Expanded) => setExpanded((cur) => (cur === which ? null : which));

  return (
    <div className="empty-state">
      <div className="empty-card welcome-hero">
        <p className="eyebrow">From spreadsheet to diagram</p>
        <h2>Start a diagram</h2>
        <p className="hint">Upload a workbook, choose a template, or build your own.</p>

        <div className="start-options">
          <button type="button" className="btn btn-primary start-option" onClick={() => fileRef.current?.click()}>
            <span className="start-option-icon" aria-hidden="true">↑</span>
            <span className="start-option-title">Upload Excel</span>
            <span className="start-option-description">Turn the rows in an .xlsx workbook into a diagram.</span>
          </button>
          <button
            type="button"
            className={`btn start-option ${expanded === "template" ? "active" : ""}`}
            aria-expanded={expanded === "template"}
            aria-controls={`${sectionId}-template`}
            onClick={() => toggle("template")}
          >
            <span className="start-option-icon" aria-hidden="true">▦</span>
            <span className="start-option-title">Use a template</span>
            <span className="start-option-description">Choose a starting structure and make it your own.</span>
          </button>
          <button type="button" className="btn start-option" onClick={onBlank}>
            <span className="start-option-icon" aria-hidden="true">+</span>
            <span className="start-option-title">Blank diagram</span>
            <span className="start-option-description">Start with an empty canvas and add shapes and connections.</span>
          </button>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept=".xlsx"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onUpload(f);
            e.target.value = "";
          }}
        />

        <button
          type="button"
          className="link-btn"
          aria-expanded={expanded === "outline"}
          aria-controls={`${sectionId}-outline`}
          onClick={() => toggle("outline")}
        >
          Or create a diagram from a text outline
        </button>

        <div id={`${sectionId}-template`} className="empty-expanded" hidden={expanded !== "template"}>
          {expanded === "template" && <TemplatesPanel onGenerate={onGenerateTemplate} />}
        </div>
        <div id={`${sectionId}-outline`} className="empty-expanded" hidden={expanded !== "outline"}>
          {expanded === "outline" && <OutlinePanel shapes={shapes} lines={lines} onGenerate={onGenerateOutline} />}
        </div>

        {recentProjects.length > 0 && (
          <section className="recent-projects" aria-labelledby={`${sectionId}-recent`}>
            <h3 id={`${sectionId}-recent`} className="section-heading">Recent projects</h3>
            <ul className="project-list">
              {recentProjects.map((project) => (
                <li key={project.id}>
                  <button
                    type="button"
                    className="btn project-row-main"
                    aria-label={`Open project ${project.name}`}
                    onClick={() => onLoadProject?.(project.id, project.name)}
                  >
                    <span className="project-name">{project.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        {samples.length > 0 && (
          <details className="examples-section">
            <summary className="section-heading">Explore examples</summary>
            <p className="hint">Open an example diagram or download its workbook to see how it is organized.</p>
            <ul className="sample-list">
              {samples.map((s) => (
                <li key={s.name}>
                  <button type="button" className="sample-item" onClick={() => onSample(s.name)} title={s.name}>
                    <span className="sample-name">{sampleLabel(s)}</span>
                    {sampleMeta(s) && <span className="sample-meta">{sampleMeta(s)}</span>}
                  </button>
                  <button
                    type="button"
                    className="sample-dl"
                    title={`Download ${s.name} — open it in Excel to see the rows behind this diagram`}
                    aria-label={`Download ${s.name}`}
                    onClick={() => downloadSample(s.name).catch(() => {})}
                  >
                    ↓ .xlsx
                  </button>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}
