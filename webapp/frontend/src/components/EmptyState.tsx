import { lazy, Suspense, useEffect, useId, useRef, useState } from "react";
import { Button, Card, Col, Row, Typography } from "antd";
import type { LineOut, ProjectInfo, SampleInfo, ShapeOut } from "../api";
import { downloadSample, getPalette, listSamples, sampleLabel, sampleMeta } from "../api";

// Same split as App.tsx's lazy panels — EmptyState is the first screen after
// login, so a static import here would pull both back into the eager bundle
// and silence the split App.tsx already does for these two (Rollup can't
// chunk-split a module that's also statically imported anywhere else).
const TemplatesPanel = lazy(() => import("./TemplatesPanel"));
const OutlinePanel = lazy(() => import("./OutlinePanel"));

const { Title, Paragraph, Text } = Typography;

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
        <Text className="eyebrow">From spreadsheet to diagram</Text>
        <Title level={2}>Start a diagram</Title>
        <Paragraph className="hint">Upload a workbook, choose a template, or build your own.</Paragraph>

        <Row gutter={[16, 16]} className="start-options-row">
          <Col xs={24} sm={8}>
            <Card
              hoverable
              className="start-option-card start-option-card-primary"
              onClick={() => fileRef.current?.click()}
            >
              <span className="start-option-icon" aria-hidden="true">↑</span>
              <div className="start-option-title">Upload Excel</div>
              <div className="start-option-description">Turn the rows in an .xlsx workbook into a diagram.</div>
            </Card>
          </Col>
          <Col xs={24} sm={8}>
            <Card
              hoverable
              className={`start-option-card ${expanded === "template" ? "active" : ""}`}
              aria-expanded={expanded === "template"}
              aria-controls={`${sectionId}-template`}
              onClick={() => toggle("template")}
            >
              <span className="start-option-icon" aria-hidden="true">▦</span>
              <div className="start-option-title">Use a template</div>
              <div className="start-option-description">Choose a starting structure and make it your own.</div>
            </Card>
          </Col>
          <Col xs={24} sm={8}>
            <Card hoverable className="start-option-card" onClick={onBlank}>
              <span className="start-option-icon" aria-hidden="true">+</span>
              <div className="start-option-title">Blank diagram</div>
              <div className="start-option-description">Start with an empty canvas and add shapes and connections.</div>
            </Card>
          </Col>
        </Row>
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

        <Button
          type="link"
          className="link-btn outline-link"
          aria-expanded={expanded === "outline"}
          aria-controls={`${sectionId}-outline`}
          onClick={() => toggle("outline")}
        >
          Or create a diagram from a text outline
        </Button>

        <div id={`${sectionId}-template`} className="empty-expanded" hidden={expanded !== "template"}>
          {expanded === "template" && (
            <Suspense fallback={null}>
              <TemplatesPanel onGenerate={onGenerateTemplate} />
            </Suspense>
          )}
        </div>
        <div id={`${sectionId}-outline`} className="empty-expanded" hidden={expanded !== "outline"}>
          {expanded === "outline" && (
            <Suspense fallback={null}>
              <OutlinePanel shapes={shapes} lines={lines} onGenerate={onGenerateOutline} />
            </Suspense>
          )}
        </div>

        {recentProjects.length > 0 && (
          <section className="recent-projects" aria-labelledby={`${sectionId}-recent`}>
            <h3 id={`${sectionId}-recent`} className="section-heading">Recent projects</h3>
            <Row gutter={[12, 12]}>
              {recentProjects.map((project) => (
                <Col xs={24} sm={12} key={project.id}>
                  <Card
                    size="small"
                    hoverable
                    className="recent-project-card"
                    onClick={() => onLoadProject?.(project.id, project.name)}
                    role="button"
                    tabIndex={0}
                    aria-label={`Open project ${project.name}`}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onLoadProject?.(project.id, project.name);
                      }
                    }}
                  >
                    {project.name}
                  </Card>
                </Col>
              ))}
            </Row>
          </section>
        )}

        {samples.length > 0 && (
          <details className="examples-section">
            <summary className="section-heading">Explore examples</summary>
            <Paragraph className="hint">Open an example diagram or download its workbook to see how it is organized.</Paragraph>
            <ul className="sample-list">
              {samples.map((s) => (
                <li key={s.name}>
                  <button type="button" className="sample-item" onClick={() => onSample(s.name)} title={s.name}>
                    <span className="sample-name">{sampleLabel(s)}</span>
                    {sampleMeta(s) && <span className="sample-meta">{sampleMeta(s)}</span>}
                  </button>
                  <Button
                    size="small"
                    title={`Download ${s.name} — open it in Excel to see the rows behind this diagram`}
                    aria-label={`Download ${s.name}`}
                    onClick={() => downloadSample(s.name).catch(() => {})}
                  >
                    ↓ .xlsx
                  </Button>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}
