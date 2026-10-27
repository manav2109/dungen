import { useCallback, useEffect, useRef, useState } from "react";
import { ConfigProvider, theme as antdTheme } from "antd";
import type { DiagramResponse, ProjectInfo } from "./api";
import {
  autoArrange,
  createBlank,
  createEdge,
  createNode,
  deleteEdge,
  deleteNode,
  deleteProject,
  duplicateNode,
  generateOutline,
  generateTemplate,
  applyCsv,
  getToken,
  listProjects,
  loadProject,
  loadSample,
  logout,
  me,
  onUnauthorized,
  redo,
  reparentNode,
  reposition as apiReposition,
  saveProject,
  setStyleRules,
  setToken,
  switchDiagram,
  undo,
  updateEdge,
  updateNode,
  uploadWorkbook,
} from "./api";
import DiagramCanvas from "./components/DiagramCanvas";
import Toolbar, { type Tool } from "./components/Toolbar";
import Palette from "./components/Palette";
import PropertiesPanel from "./components/PropertiesPanel";
import CsvPanel from "./components/CsvPanel";
import TemplatesPanel from "./components/TemplatesPanel";
import OutlinePanel from "./components/OutlinePanel";
import StyleRulesPanel from "./components/StyleRulesPanel";
import ProjectsPanel from "./components/ProjectsPanel";
import VoicePanel from "./components/VoicePanel";
import LoginScreen from "./components/LoginScreen";
import EmptyState from "./components/EmptyState";
import Sidebar, { SIDEBAR_DEFAULT } from "./components/Sidebar";
import SaveDialog from "./components/SaveDialog";
import ExportPanel from "./components/ExportPanel";
import { usePersistentState } from "./usePersistentState";
import "./styles.css";

type SidebarTab =
  | "properties"
  | "palette"
  | "csv"
  | "templates"
  | "outline"
  | "voice"
  | "style"
  | "projects";

// Icons for the collapsed rail — 18px, stroke-based so they pick up the
// button's text color (grey normally, white when active).
function railIcon(children: React.ReactNode) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 18 18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

const ICONS = {
  // sliders
  properties: railIcon(
    <>
      <path d="M3 5h12M3 9h12M3 13h12" />
      <circle cx="7" cy="5" r="1.8" fill="currentColor" stroke="none" />
      <circle cx="12" cy="9" r="1.8" fill="currentColor" stroke="none" />
      <circle cx="6" cy="13" r="1.8" fill="currentColor" stroke="none" />
    </>
  ),
  // square + circle shapes
  palette: railIcon(
    <>
      <rect x="2.5" y="2.5" width="7.5" height="7.5" rx="1" />
      <circle cx="12" cy="12" r="3.5" />
    </>
  ),
  // table grid
  csv: railIcon(
    <>
      <rect x="2.5" y="3.5" width="13" height="11" rx="1" />
      <path d="M2.5 7h13M7 3.5v11M11.5 3.5v11" />
    </>
  ),
  // page layout blocks
  templates: railIcon(
    <>
      <rect x="2.5" y="2.5" width="13" height="13" rx="1" />
      <path d="M2.5 6.5h13M8 6.5v9" />
    </>
  ),
  // indented list
  outline: railIcon(
    <>
      <path d="M3 4h9M6 9h9M6 14h9" />
      <circle cx="3.5" cy="9" r="0.8" fill="currentColor" stroke="none" />
      <circle cx="3.5" cy="14" r="0.8" fill="currentColor" stroke="none" />
    </>
  ),
  // microphone
  voice: railIcon(
    <>
      <rect x="6.75" y="2" width="4.5" height="8" rx="2.25" />
      <path d="M4 8.5a5 5 0 0 0 10 0M9 13.5V16M6.5 16h5" />
    </>
  ),
  // paint drop
  style: railIcon(
    <>
      <path d="M9 2.5c2.6 3.2 4.5 5.7 4.5 8a4.5 4.5 0 0 1-9 0c0-2.3 1.9-4.8 4.5-8z" />
    </>
  ),
  // folder
  projects: railIcon(
    <>
      <path d="M2.5 5a1 1 0 0 1 1-1h3.6l1.6 2h5.8a1 1 0 0 1 1 1v6.5a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V5z" />
    </>
  ),
};

// [key, full label, icon for the collapsed rail]
const SIDEBAR_TABS: [SidebarTab, string, React.ReactNode][] = [
  ["properties", "Properties", ICONS.properties],
  ["palette", "Palette", ICONS.palette],
  ["csv", "CSV", ICONS.csv],
  ["templates", "Templates", ICONS.templates],
  ["outline", "Outline", ICONS.outline],
  ["voice", "Voice", ICONS.voice],
  ["style", "Style rules", ICONS.style],
  ["projects", "Projects", ICONS.projects],
];

const SIDEBAR_GROUPS: { label: string; keys: SidebarTab[] }[] = [
  { label: "Shapes", keys: ["palette"] },
  { label: "Properties", keys: ["properties"] },
  { label: "Create", keys: ["templates", "outline", "voice"] },
  { label: "Data & Styles", keys: ["csv", "style"] },
  { label: "Projects", keys: ["projects"] },
];

function download(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function isTypingTarget(el: EventTarget | null): boolean {
  const e = el as HTMLElement | null;
  if (!e) return false;
  const tag = e.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.isContentEditable;
}

function DiagramApp({ username, onLogout }: { username: string; onLogout: () => void }) {
  const [diagram, setDiagram] = useState<DiagramResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [tool, setTool] = useState<Tool>("select");
  const [search, setSearch] = useState("");
  const [tab, setTab] = usePersistentState<SidebarTab>("drawgen.sidebarTab", "properties");
  const [sidebarWidth, setSidebarWidth] = usePersistentState("drawgen.sidebarWidth", SIDEBAR_DEFAULT);
  const [sidebarCollapsed, setSidebarCollapsed] = usePersistentState("drawgen.sidebarCollapsed", false);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null);
  const [currentProjectName, setCurrentProjectName] = useState<string>("");
  const [autosaveAt, setAutosaveAt] = useState<number | null>(null);
  // Every successful mutation marks the diagram dirty; saving clears it. Drives
  // both the toolbar's saved/unsaved indicator and the leave-page guard.
  const [dirty, setDirty] = useState(false);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [exportPanelOpen, setExportPanelOpen] = useState(false);
  // Where the open diagram came from ("Sample: S1_…", "Uploaded: foo.xlsx", …).
  // The API response only carries the diagram itself, so provenance is tracked
  // here at the point of loading.
  const [source, setSource] = useState<string | null>(null);
  // Set only when the diagram came from a bundled sample, which is the one
  // source whose workbook still exists on the server and can be handed back.
  // An uploaded file was parsed and discarded; a template/outline never had one.
  const [sourceSample, setSourceSample] = useState<string | null>(null);
  const diagramRef = useRef(diagram);
  diagramRef.current = diagram;

  const handleErr = (e: any) => {
    const status = e?.response?.status;
    const detail = e?.response?.data?.detail;
    if (status && status >= 500) {
      console.error("server error:", e);
      setError("Something went wrong on the server. Try again — if it keeps happening, reload the page.");
    } else if (detail) {
      // 4xx details from the API are already written for a human (e.g. "Unknown entity_type: foo").
      setError(detail);
    } else if (e?.message === "Network Error") {
      setError("Can't reach the server. Check your connection and try again.");
    } else {
      setError(e?.message || "That didn't work. Try again.");
    }
  };

  const refreshProjects = useCallback(() => {
    listProjects().then(setProjects).catch(() => {});
  }, []);

  useEffect(() => {
    refreshProjects();
  }, [refreshProjects]);

  // `after` fires once the new diagram is in state — used by project-load to
  // re-attach the project id/name once loading actually succeeds.
  const runLoad = useCallback((p: Promise<DiagramResponse>, sourceLabel: string | null = null,
                               after?: (d: DiagramResponse) => void, sampleName: string | null = null) => {
    setLoading(true);
    setSource(sourceLabel);
    setSourceSample(sampleName);
    setError(null);
    setSelectedNodeIds([]);
    setSelectedEdgeId(null);
    setCurrentProjectId(null);
    setCurrentProjectName("");
    setAutosaveAt(null);
    p.then((d) => {
      setDiagram(d);
      setDirty(false); // freshly loaded == exactly what the server has
      after?.(d);
    })
      .catch(handleErr)
      .finally(() => setLoading(false));
  }, []);

  const runMutate = useCallback(
    (p: Promise<DiagramResponse>, after?: (d: DiagramResponse, prevNodeIds: Set<string>) => void) => {
      const prevIds = new Set((diagramRef.current?.nodes ?? []).map((n) => n.id));
      setBusy(true);
      setError(null);
      p.then((d) => {
        setDiagram(d);
        setDirty(true);
        after?.(d, prevIds);
      })
        .catch(handleErr)
        .finally(() => setBusy(false));
    },
    []
  );

  // ---------- load / bootstrap ----------
  const onUpload = useCallback(
    (file: File) => runLoad(uploadWorkbook(file), `Uploaded: ${file.name}`),
    [runLoad]
  );
  const onSample = useCallback(
    (name: string) => runLoad(loadSample(name), `Sample: ${name}`, undefined, name),
    [runLoad]
  );
  const onBlank = useCallback(() => runLoad(createBlank(), "Blank canvas"), [runLoad]);
  const onSwitchDiagram = useCallback(
    (id: string) => {
      if (!diagram) return;
      // Switching sheets inside the same workbook doesn't change where it came from.
      runLoad(switchDiagram(diagram.session_id, id), source, undefined, sourceSample);
    },
    [diagram, runLoad, source, sourceSample]
  );

  // ---------- saved projects ----------
  const onLoadProject = useCallback(
    (id: string, name: string) => {
      runLoad(loadProject(id), `Project: ${name}`, () => {
        setCurrentProjectId(id);
        setCurrentProjectName(name);
        setAutosaveAt(Date.now());
      });
    },
    [runLoad]
  );

  const doSave = useCallback(
    (name: string, projectId: string | null, silent = false) => {
      if (!diagram) return;
      if (!silent) {
        setBusy(true);
        setError(null);
      }
      saveProject(diagram.session_id, name, projectId)
        .then((info) => {
          setCurrentProjectId(info.id);
          setCurrentProjectName(info.name);
          setAutosaveAt(Date.now());
          setDirty(false);
          refreshProjects();
        })
        .catch((e) => {
          // Autosave failing quietly (e.g. a transient network blip) shouldn't
          // interrupt someone mid-edit with an error banner — explicit Save
          // still surfaces failures normally.
          if (silent) console.warn("autosave failed:", e);
          else handleErr(e);
        })
        .finally(() => {
          if (!silent) setBusy(false);
        });
    },
    [diagram, refreshProjects]
  );

  const onSaveProject = useCallback((name: string) => doSave(name, currentProjectId), [doSave, currentProjectId]);
  const onSaveProjectAsCopy = useCallback((name: string) => doSave(name, null), [doSave]);

  // ---------- auto-save ----------
  // While the open diagram is tied to a saved project, silently re-save it
  // every 2 minutes so a crash/restart doesn't lose more than that much
  // work — on top of, not instead of, the explicit Save button.
  const AUTOSAVE_INTERVAL_MS = 2 * 60 * 1000;
  const currentProjectIdRef = useRef(currentProjectId);
  currentProjectIdRef.current = currentProjectId;
  const currentProjectNameRef = useRef(currentProjectName);
  currentProjectNameRef.current = currentProjectName;

  useEffect(() => {
    const t = setInterval(() => {
      const pid = currentProjectIdRef.current;
      if (pid) doSave(currentProjectNameRef.current, pid, true);
    }, AUTOSAVE_INTERVAL_MS);
    return () => clearInterval(t);
  }, [doSave]);

  const onQuickSave = useCallback(() => {
    if (currentProjectId) {
      onSaveProject(currentProjectName);
      return;
    }
    setSaveDialogOpen(true);
  }, [currentProjectId, currentProjectName, onSaveProject]);

  const onDeleteProject = useCallback(
    (id: string) => {
      deleteProject(id)
        .then(() => {
          if (id === currentProjectId) {
            setCurrentProjectId(null);
            setCurrentProjectName("");
          }
          refreshProjects();
        })
        .catch(handleErr);
    },
    [currentProjectId, refreshProjects]
  );

  // ---------- selection ----------
  const onSelectNode = useCallback((id: string | null, additive = false) => {
    setSelectedEdgeId(null);
    if (id === null) {
      setSelectedNodeIds([]);
      return;
    }
    if (additive) {
      setSelectedNodeIds((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
    } else {
      setSelectedNodeIds([id]);
    }
  }, []);

  const onSelectEdge = useCallback((id: string | null) => {
    setSelectedNodeIds([]);
    setSelectedEdgeId(id);
  }, []);

  // ---------- node/edge mutation ----------
  const onDragEnd = useCallback(
    (nodeId: string, x: number, y: number) => {
      if (!diagram) return;
      runMutate(apiReposition(diagram.session_id, nodeId, x, y));
    },
    [diagram, runMutate]
  );

  const onCreateFromPalette = useCallback(
    (entityType: string) => {
      if (!diagram) return;
      const x = diagram.canvas_w / 2 - 60;
      const y = diagram.canvas_h / 2 - 25;
      runMutate(createNode(diagram.session_id, entityType, { x, y }), (d, prevIds) => {
        const added = d.nodes.find((n) => !prevIds.has(n.id));
        if (added) onSelectNode(added.id);
      });
    },
    [diagram, runMutate, onSelectNode]
  );

  const onDropCreate = useCallback(
    (entityType: string, x: number, y: number) => {
      if (!diagram) return;
      runMutate(createNode(diagram.session_id, entityType, { x, y }), (d, prevIds) => {
        const added = d.nodes.find((n) => !prevIds.has(n.id));
        if (added) onSelectNode(added.id);
      });
    },
    [diagram, runMutate, onSelectNode]
  );

  const onUpdateNode = useCallback(
    (nodeId: string, patch: Parameters<typeof updateNode>[2]) => {
      if (!diagram) return;
      runMutate(updateNode(diagram.session_id, nodeId, patch));
    },
    [diagram, runMutate]
  );

  const onDeleteNode = useCallback(
    (nodeId: string) => {
      if (!diagram) return;
      setSelectedNodeIds([]);
      setSelectedEdgeId(null);
      runMutate(deleteNode(diagram.session_id, nodeId));
    },
    [diagram, runMutate]
  );

  const onBulkDeleteNodes = useCallback(
    async (ids: string[]) => {
      if (!diagram) return;
      setSelectedNodeIds([]);
      setSelectedEdgeId(null);
      setBusy(true);
      setError(null);
      let sid = diagram.session_id;
      let last: DiagramResponse | null = null;
      for (const id of ids) {
        try {
          last = await deleteNode(sid, id);
        } catch (e: any) {
          if (e?.response?.status !== 404) {
            handleErr(e);
            break;
          }
          // already gone (deleted as a descendant of an earlier node in this batch) — continue
        }
      }
      if (last) setDiagram(last);
      setBusy(false);
    },
    [diagram]
  );

  const onDuplicateNode = useCallback(
    (nodeId: string) => {
      if (!diagram) return;
      runMutate(duplicateNode(diagram.session_id, nodeId), (d, prevIds) => {
        const added = d.nodes.find((n) => !prevIds.has(n.id));
        if (added) onSelectNode(added.id);
      });
    },
    [diagram, runMutate, onSelectNode]
  );

  const onReparentNode = useCallback(
    (nodeId: string, parent: string) => {
      if (!diagram) return;
      runMutate(reparentNode(diagram.session_id, nodeId, parent));
    },
    [diagram, runMutate]
  );

  const onConnectCreate = useCallback(
    (sourceId: string, targetId: string) => {
      if (!diagram) return;
      const relationType = diagram.lines[0]?.relation_type || "association";
      runMutate(createEdge(diagram.session_id, sourceId, targetId, relationType));
    },
    [diagram, runMutate]
  );

  const onUpdateEdge = useCallback(
    (edgeId: string, patch: Parameters<typeof updateEdge>[2]) => {
      if (!diagram) return;
      runMutate(updateEdge(diagram.session_id, edgeId, patch));
    },
    [diagram, runMutate]
  );

  const onDeleteEdge = useCallback(
    (edgeId: string) => {
      if (!diagram) return;
      setSelectedEdgeId(null);
      runMutate(deleteEdge(diagram.session_id, edgeId));
    },
    [diagram, runMutate]
  );

  // ---------- layout / history ----------
  const onAutoArrange = useCallback(() => {
    if (!diagram) return;
    runMutate(autoArrange(diagram.session_id));
  }, [diagram, runMutate]);

  const onSetDirection = useCallback(
    (dir: "TB" | "LR") => {
      if (!diagram) return;
      runMutate(autoArrange(diagram.session_id, dir));
    },
    [diagram, runMutate]
  );

  const onUndo = useCallback(() => {
    if (!diagram) return;
    runMutate(undo(diagram.session_id));
  }, [diagram, runMutate]);

  const onRedo = useCallback(() => {
    if (!diagram) return;
    runMutate(redo(diagram.session_id));
  }, [diagram, runMutate]);

  // ---------- CSV / templates / outline / style rules ----------
  const onApplyCsv = useCallback(
    (nodesCsv: string, edgesCsv: string, shapesCsv: string, linesCsv: string) => {
      if (!diagram) return;
      runMutate(applyCsv(diagram.session_id, nodesCsv, edgesCsv, shapesCsv, linesCsv));
    },
    [diagram, runMutate]
  );

  const onGenerateTemplate = useCallback(
    (name: string, params: Record<string, string>) =>
      runLoad(generateTemplate(name, params), `Template: ${name}`),
    [runLoad]
  );

  const onGenerateOutline = useCallback(
    (text: string, entityType: string, relationType: string) =>
      runLoad(generateOutline(text, entityType, relationType), "Generated from outline"),
    [runLoad]
  );

  const onApplyStyleRules = useCallback(
    (rulesText: string) => {
      if (!diagram) return;
      runMutate(setStyleRules(diagram.session_id, rulesText));
    },
    [diagram, runMutate]
  );

  const onDownload = useCallback(
    (kind: "svg" | "drawio" | "html") => {
      if (!diagram) return;
      const base = diagram.title || "diagram";
      if (kind === "svg") download(`${base}.svg`, diagram.svg, "image/svg+xml");
      else if (kind === "drawio") download(`${base}.drawio`, diagram.drawio, "application/xml");
      else download(`${base}.html`, diagram.html, "text/html");
    },
    [diagram]
  );

  // ---------- keyboard shortcuts ----------
  useEffect(() => {
    const onKeyDown = (ev: KeyboardEvent) => {
      if (saveDialogOpen) {
        if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s") ev.preventDefault();
        return;
      }
      // Save is the one shortcut that must survive focus being in a text field —
      // it also has to beat the browser's own "save page" dialog to preventDefault.
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s") {
        ev.preventDefault();
        if (diagramRef.current) onQuickSave();
        return;
      }
      if (isTypingTarget(ev.target)) return;
      const d = diagramRef.current;
      if (!d) return;
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "z") {
        ev.preventDefault();
        if (ev.shiftKey) onRedo();
        else onUndo();
        return;
      }
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "y") {
        ev.preventDefault();
        onRedo();
        return;
      }
      if (ev.key === "v" || ev.key === "V") setTool("select");
      else if (ev.key === "c" || ev.key === "C") setTool("connect");
      else if (ev.key === "Escape") {
        setSelectedNodeIds([]);
        setSelectedEdgeId(null);
      } else if (ev.key === "Delete" || ev.key === "Backspace") {
        if (selectedEdgeId) onDeleteEdge(selectedEdgeId);
        else if (selectedNodeIds.length === 1) onDeleteNode(selectedNodeIds[0]);
        else if (selectedNodeIds.length > 1) onBulkDeleteNodes(selectedNodeIds);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    selectedNodeIds,
    selectedEdgeId,
    onUndo,
    onRedo,
    onDeleteEdge,
    onDeleteNode,
    onBulkDeleteNodes,
    onQuickSave,
    saveDialogOpen,
  ]);

  // ---------- leave-page guard ----------
  // Only edits made since the last save are at risk: autosave covers a diagram
  // already tied to a project, but an unsaved one lives purely in the session.
  useEffect(() => {
    if (!dirty) return;
    const warn = (ev: BeforeUnloadEvent) => {
      ev.preventDefault();
      ev.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  return (
    <div className="app">
      {saveDialogOpen && <SaveDialog initialName={diagram?.title || "Untitled"} onSave={onSaveProject} onClose={() => setSaveDialogOpen(false)} />}
      {exportPanelOpen && diagram && (
        <ExportPanel
          diagram={diagram}
          projectName={currentProjectName}
          onDownloadSimple={onDownload}
          onClose={() => setExportPanelOpen(false)}
          onSettingsSaved={(settings) => setDiagram((d) => (d ? { ...d, export_settings: settings } : d))}
        />
      )}
      <Toolbar
        hasDiagram={!!diagram}
        title={currentProjectName || diagram?.title || null}
        loading={loading}
        busy={busy}
        error={error}
        onDismissError={() => setError(null)}
        source={source}
        sourceSample={sourceSample}
        nodeCount={diagram?.nodes.length ?? 0}
        edgeCount={diagram?.edges.length ?? 0}
        diagrams={diagram?.diagrams ?? []}
        activeDiagramId={diagram?.diagram_id ?? ""}
        direction={diagram?.direction ?? "top-down"}
        tool={tool}
        search={search}
        onUpload={onUpload}
        onSample={onSample}
        onBlank={onBlank}
        onSwitchDiagram={onSwitchDiagram}
        onSetDirection={onSetDirection}
        onAutoArrange={onAutoArrange}
        onUndo={onUndo}
        onRedo={onRedo}
        onSetTool={setTool}
        onSearchChange={setSearch}
        onOpenExport={() => setExportPanelOpen(true)}
        hasSavedProject={!!currentProjectId}
        onQuickSave={onQuickSave}
        lastSavedAt={currentProjectId ? autosaveAt : null}
        dirty={dirty}
        username={username}
        onLogout={onLogout}
      />
      <div className="body">
        <div className="canvas-area">
          {diagram ? (
            <DiagramCanvas
              // Remount on a genuinely different diagram so the canvas re-fits to
              // it; plain edits keep the same key and so keep the user's view.
              key={`${diagram.session_id}:${diagram.diagram_id}`}
              svg={diagram.svg}
              nodes={diagram.nodes}
              edges={diagram.edges}
              connections={diagram.connections}
              selectedNodeIds={selectedNodeIds}
              selectedEdgeId={selectedEdgeId}
              tool={tool}
              search={search}
              onSelectNode={onSelectNode}
              onSelectEdge={onSelectEdge}
              onDragEnd={onDragEnd}
              onConnectCreate={onConnectCreate}
              onDropCreate={onDropCreate}
              busy={busy}
            />
          ) : (
            <EmptyState
              projects={projects}
              onLoadProject={onLoadProject}
              onBlank={onBlank}
              onSample={onSample}
              onUpload={onUpload}
              onGenerateTemplate={onGenerateTemplate}
              onGenerateOutline={onGenerateOutline}
            />
          )}
        </div>
        {diagram && (
          <Sidebar
            tabs={SIDEBAR_TABS}
            groups={SIDEBAR_GROUPS}
            tab={tab}
            onTabChange={setTab}
            width={sidebarWidth}
            onWidthChange={setSidebarWidth}
            collapsed={sidebarCollapsed}
            onSetCollapsed={setSidebarCollapsed}
          >
            {tab === "properties" && (
              <PropertiesPanel
                nodes={diagram.nodes}
                edges={diagram.edges}
                shapes={diagram.shapes}
                lines={diagram.lines}
                connections={diagram.connections}
                selectedNodeIds={selectedNodeIds}
                selectedEdgeId={selectedEdgeId}
                onSelectNode={onSelectNode}
                onUpdateNode={onUpdateNode}
                onDeleteNode={onDeleteNode}
                onDuplicateNode={onDuplicateNode}
                onReparentNode={onReparentNode}
                onBulkDeleteNodes={onBulkDeleteNodes}
                onUpdateEdge={onUpdateEdge}
                onDeleteEdge={onDeleteEdge}
              />
            )}
            {tab === "palette" && <Palette shapes={diagram.shapes} onCreate={onCreateFromPalette} />}
            {tab === "csv" && (
              <CsvPanel
                unknownTypes={diagram.unknown_types}
                shapes={diagram.shapes}
                lines={diagram.lines}
                onApply={onApplyCsv}
              />
            )}
            {tab === "templates" && <TemplatesPanel onGenerate={onGenerateTemplate} />}
            {tab === "outline" && (
              <OutlinePanel shapes={diagram.shapes} lines={diagram.lines} onGenerate={onGenerateOutline} />
            )}
            {tab === "voice" && (
              <VoicePanel shapes={diagram.shapes} lines={diagram.lines} onGenerate={onGenerateOutline} />
            )}
            {tab === "style" && <StyleRulesPanel rulesText={diagram.style_rules} onApply={onApplyStyleRules} />}
            {tab === "projects" && (
              <ProjectsPanel
                projects={projects}
                currentProjectId={currentProjectId}
                currentName={currentProjectName || diagram.title}
                busy={busy}
                onSave={onSaveProject}
                onSaveAsCopy={onSaveProjectAsCopy}
                onLoad={onLoadProject}
                onDelete={onDeleteProject}
              />
            )}
          </Sidebar>
        )}
      </div>
    </div>
  );
}

// ---------- auth gate ----------
// Wraps DiagramApp: validates any stored token on mount (a token can be
// stale — expired, or the DB it was issued against got wiped), shows
// LoginScreen otherwise, and drops back to LoginScreen on any 401 from the
// API (onUnauthorized, wired in api.ts) rather than each caller handling it.
export default function App() {
  const [checked, setChecked] = useState(false);
  const [user, setUser] = useState<{ username: string } | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setChecked(true);
      return;
    }
    me()
      .then((u) => setUser(u))
      .catch(() => setToken(null))
      .finally(() => setChecked(true));
  }, []);

  useEffect(() => {
    onUnauthorized.handler = () => setUser(null);
    return () => {
      onUnauthorized.handler = null;
    };
  }, []);

  const onAuthed = useCallback((token: string, username: string) => {
    setToken(token);
    setUser({ username });
  }, []);

  const onLogout = useCallback(() => {
    // Fire-and-forget: local logout must succeed even if this fails (dead
    // network, already-expired token) — the point is leaving no stale
    // session on the server, not blocking the user from getting back to
    // the login screen.
    logout().catch(() => {});
    setToken(null);
    setUser(null);
  }, []);

  if (!checked) return null;
  return (
    <ConfigProvider
      theme={{
        algorithm: antdTheme.defaultAlgorithm,
        // Mirror styles.css's :root tokens so AntD components read as part of
        // the product, not as a generic library dropped on top of it.
        token: {
          colorPrimary: "#4265d6",
          colorPrimaryHover: "#3453bd",
          colorPrimaryBg: "#eef2ff",
          colorText: "#253047",
          colorTextSecondary: "#647087",
          colorBorder: "#e2e7ef",
          colorBorderSecondary: "#ccd4e0",
          colorBgContainer: "#ffffff",
          colorBgLayout: "#f5f7fb",
          colorError: "#b33737",
          borderRadius: 8,
          fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
          fontSize: 14,
        },
      }}
    >
      {!user ? (
        <LoginScreen onAuthed={onAuthed} />
      ) : (
        <DiagramApp key={user.username} username={user.username} onLogout={onLogout} />
      )}
    </ConfigProvider>
  );
}
