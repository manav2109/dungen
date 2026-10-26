import { useEffect, useRef, useState } from "react";
import type { DiagramInfo, SampleInfo } from "../api";
import { downloadSample, listSamples, sampleLabel, sampleMeta } from "../api";
import ShortcutsHelp from "./ShortcutsHelp";
import ActionMenu from "./ActionMenu";
import Icon from "./Icon";

export type Tool = "select" | "connect";

interface Props {
  hasDiagram: boolean;
  title: string | null;
  loading: boolean;
  busy: boolean;
  error: string | null;
  onDismissError: () => void;
  source: string | null;
  sourceSample: string | null;
  nodeCount: number;
  edgeCount: number;
  diagrams: DiagramInfo[];
  activeDiagramId: string;
  direction: string;
  tool: Tool;
  search: string;
  onUpload: (file: File) => void;
  onSample: (name: string) => void;
  onBlank: () => void;
  onSwitchDiagram: (id: string) => void;
  onSetDirection: (dir: "TB" | "LR") => void;
  onAutoArrange: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onSetTool: (tool: Tool) => void;
  onSearchChange: (s: string) => void;
  onOpenExport: () => void;
  hasSavedProject: boolean;
  onQuickSave: () => void;
  lastSavedAt: number | null;
  dirty: boolean;
  username: string;
  onLogout: () => void;
}

function useRelativeTime(ts: number | null): string | null {
  const [, force] = useState(0);
  useEffect(() => {
    if (ts == null) return;
    const id = setInterval(() => force((n) => n + 1), 15000);
    return () => clearInterval(id);
  }, [ts]);
  if (ts == null) return null;
  const secs = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (secs < 10) return "Saved just now";
  if (secs < 60) return `Saved ${secs}s ago`;
  return `Saved ${Math.round(secs / 60)}m ago`;
}

export default function Toolbar({
  hasDiagram, title, loading, busy, error, onDismissError, source, sourceSample,
  nodeCount, edgeCount, diagrams, activeDiagramId, direction, tool, search,
  onUpload, onSample, onBlank, onSwitchDiagram, onSetDirection, onAutoArrange,
  onUndo, onRedo, onSetTool, onSearchChange, onOpenExport, hasSavedProject,
  onQuickSave, lastSavedAt, dirty, username, onLogout,
}: Props) {
  const [samples, setSamples] = useState<SampleInfo[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  const disabled = loading || busy;
  const savedLabel = useRelativeTime(lastSavedAt);
  useEffect(() => { listSamples().then(setSamples).catch(() => setSamples([])); }, []);

  return (
    <>
      <header className="topbar">
        <div className="brand"><span className="brand-mark" aria-hidden="true">D</span>DrawGen</div>
        <span className="header-divider" aria-hidden="true" />
        <div className="document-title">
          <span className="title-name" title={title || undefined}>{loading ? "Opening diagram…" : title || "Your diagram workspace"}</span>
          {hasDiagram && <div className="document-meta">
            {source && (sourceSample ? (
              <button className="source-link" title={`Download original workbook: ${sourceSample}`} onClick={() => downloadSample(sourceSample).catch(() => {})}>{source}<Icon name="download" /></button>
            ) : <span className="source-label" title={source}>{source}</span>)}
            <span className="title-stats">{nodeCount} shapes · {edgeCount} connections</span>
          </div>}
        </div>
        <div className="header-actions">
          {hasDiagram && <span className={`save-status ${dirty ? "unsaved-label" : "saved-label"}`} role="status">{dirty ? "Unsaved changes" : savedLabel || "Not saved yet"}</span>}
          <ActionMenu label={<><Icon name="plus" />New / Open</>} className="new-menu">
            <p className="menu-heading">Start a diagram</p>
            <button className="menu-item" disabled={disabled} onClick={() => fileRef.current?.click()}><Icon name="upload" />Upload Excel<span className="menu-detail">.xlsx</span></button>
            <button className="menu-item" disabled={disabled} onClick={onBlank}><Icon name="plus" />Blank diagram</button>
            {samples.length > 0 && <><p className="menu-heading">Sample workbooks</p><div className="menu-samples">
              {samples.map((sample) => <button key={sample.name} className="menu-item sample-menu-item" disabled={disabled} onClick={() => onSample(sample.name)} title={sample.name}>
                <span>{sampleLabel(sample)}<small>{sampleMeta(sample)}</small></span>
              </button>)}
            </div></>}
          </ActionMenu>
          <input ref={fileRef} type="file" accept=".xlsx" hidden onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onUpload(file);
            event.target.value = "";
          }} />
          {hasDiagram && <>
            <button className="btn btn-primary" onClick={onQuickSave} disabled={disabled} title="Save diagram (Ctrl / ⌘ + S)">{hasSavedProject ? "Save" : "Save as…"}</button>
            <button className="btn btn-quiet" disabled={disabled} onClick={onOpenExport}><Icon name="download" />Export</button>
          </>}
          <ActionMenu label={<><Icon name="user" /><span className="account-name">{username}</span></>} ariaLabel={`Account: ${username}`} className="account-menu">
            <p className="menu-heading">Signed in as {username}</p>
            <button className="menu-item" onClick={onLogout}>Log out</button>
          </ActionMenu>
        </div>
      </header>
      {hasDiagram && <div className="editor-toolbar" aria-label="Diagram editing tools">
        <div className="toolbar-group">
          <div className="tool-toggle" role="group" aria-label="Editing mode">
            <button className={tool === "select" ? "active" : ""} aria-pressed={tool === "select"} onClick={() => onSetTool("select")} disabled={disabled} title="Select shapes (V)"><Icon name="cursor" />Select</button>
            <button className={tool === "connect" ? "active" : ""} aria-pressed={tool === "connect"} onClick={() => onSetTool("connect")} disabled={disabled} title="Connect shapes (C)"><Icon name="connect" />Connect</button>
          </div>
          <span className="sep" aria-hidden="true" />
          <button className="btn btn-quiet icon-button" onClick={onUndo} disabled={disabled} aria-label="Undo" title="Undo (Ctrl / ⌘ + Z)"><Icon name="undo" /></button>
          <button className="btn btn-quiet icon-button" onClick={onRedo} disabled={disabled} aria-label="Redo" title="Redo (Ctrl / ⌘ + Shift + Z)"><Icon name="redo" /></button>
        </div>
        <span className="sep" aria-hidden="true" />
        <div className="toolbar-group layout-tools">
          <label className="toolbar-label">Layout
            <select value={direction.startsWith("top") ? "TB" : "LR"} onChange={(event) => onSetDirection(event.target.value as "TB" | "LR")} disabled={disabled}>
              <option value="TB">Top to bottom</option><option value="LR">Left to right</option>
            </select>
          </label>
          <button className="btn btn-quiet" onClick={onAutoArrange} disabled={disabled}><Icon name="layout" />Auto-arrange</button>
        </div>
        {diagrams.length > 1 && <label className="toolbar-label diagram-switcher">Diagram
          <select value={activeDiagramId} onChange={(event) => onSwitchDiagram(event.target.value)} disabled={disabled}>{diagrams.map((diagram) => <option key={diagram.id} value={diagram.id}>{diagram.title || diagram.id}</option>)}</select>
        </label>}
        <div className="toolbar-trailing">
          <label className="canvas-search"><Icon name="search" /><input type="search" placeholder="Search shapes…" aria-label="Search shapes on canvas" value={search} onChange={(event) => onSearchChange(event.target.value)} /></label>
          <ShortcutsHelp />
        </div>
      </div>}
      {error && <div className="app-notice" role="alert"><span>{error}</span><button className="error-dismiss" onClick={onDismissError} aria-label="Dismiss error">×</button></div>}
    </>
  );
}
