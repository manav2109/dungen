import axios from "axios";

// ---------- core entities ----------
export interface NodeOut {
  id: string;
  label: string;
  type: string;
  x: number;
  y: number;
  w: number;
  h: number;
  parent?: string | null;
  rank_hint: number;
  order_hint: number;
  w_override?: number | null;
  h_override?: number | null;
  fill_override: string;
  stroke_override: string;
  metadata: string;
}

export interface EdgeOut {
  id: string;
  source: string;
  target: string;
  label: string;
  relation: string;
  waypoint_hint: string;
  source_port: string;
  target_port: string;
}

export interface ConnectionOut {
  edge_id: string;
  other_id: string;
  other_label: string;
  label: string;
  dir: "in" | "out";
}

export interface DiagramInfo {
  id: string;
  title: string;
  node_count: number;
}

export interface ShapeOut {
  entity_type: string;
  family: string;
  shape: string;
  fill: string;
  stroke: string;
  auto: string;
  default_w: number;
  default_h: number;
  min_w: number;
  min_h: number;
}

export interface LineOut {
  relation_type: string;
  family: string;
  style: string;
  width: number;
  source_end: string;
  target_end: string;
  routing: string;
  label_pos: string;
  color: string;
}

export interface DiagramResponse {
  session_id: string;
  diagram_id: string;
  title: string;
  direction: string;
  svg: string;
  drawio: string;
  html: string;
  canvas_w: number;
  canvas_h: number;
  nodes: NodeOut[];
  edges: EdgeOut[];
  connections: Record<string, ConnectionOut[]>;
  diagrams: DiagramInfo[];
  shapes: ShapeOut[];
  lines: LineOut[];
  style_rules: string;
  unknown_types: string[];
  // Opaque to this app's own code too, except the Export panel — see
  // ExportPanel.tsx. Round-trips through project save/load untouched.
  export_settings: Record<string, unknown>;
}

export interface PaletteResponse {
  shapes: ShapeOut[];
  lines: LineOut[];
}

export interface TemplateField {
  key: string;
  label: string;
  default: string;
}

export interface TemplateInfo {
  description: string;
  fields: TemplateField[];
}

export type TemplatesResponse = Record<string, TemplateInfo>;

export interface ProjectInfo {
  id: string;
  name: string;
  created_at: number;
  updated_at: number;
}

// In dev, Vite proxies /api -> the FastAPI backend (see vite.config.ts).
// In prod, point VITE_API_BASE at wherever the backend is deployed.
const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || "/api",
});

// ---------- auth ----------
const TOKEN_KEY = "drawgen_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

client.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Fires on any 401 (expired/invalid token) — App listens for this to drop
// back to the login screen instead of every caller having to check.
export const onUnauthorized = { handler: null as (() => void) | null };

client.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401) {
      setToken(null);
      onUnauthorized.handler?.();
    }
    return Promise.reject(err);
  }
);

export interface AuthResponse {
  token: string;
  username: string;
}

export async function signup(username: string, password: string): Promise<AuthResponse> {
  const r = await client.post<AuthResponse>("/auth/signup", { username, password });
  return r.data;
}

export async function login(username: string, password: string): Promise<AuthResponse> {
  const r = await client.post<AuthResponse>("/auth/login", { username, password });
  return r.data;
}

export async function me(): Promise<{ username: string }> {
  const r = await client.get<{ username: string }>("/auth/me");
  return r.data;
}

export async function logout(): Promise<void> {
  await client.post("/auth/logout");
}

// ---------- load / bootstrap ----------
export interface SampleInfo {
  name: string;
  title: string;
  // null when the workbook couldn't be read (e.g. it's open in Excel)
  diagrams: number | null;
  nodes: number | null;
  edges: number | null;
}

/** "51 shapes · 89 links", or null when the workbook couldn't be inspected. */
export function sampleMeta(s: SampleInfo): string | null {
  if (s.nodes == null || s.edges == null) return null;
  const extra = s.diagrams && s.diagrams > 1 ? ` · ${s.diagrams} diagrams` : "";
  return `${s.nodes} shapes · ${s.edges} links${extra}`;
}

/** Human label for a sample: its own title if the workbook gives one, otherwise
 * the filename tidied up (strip the extension and the S1_/S2_ ordering prefix). */
export function sampleLabel(s: SampleInfo): string {
  if (s.title) return s.title;
  return s.name
    .replace(/\.xlsx$/i, "")
    .replace(/^S\d+_/, "")
    .replace(/[_-]+/g, " ");
}

export async function listSamples(): Promise<SampleInfo[]> {
  const r = await client.get<SampleInfo[]>("/samples");
  return r.data;
}

/** Download a sample workbook to disk.
 *
 * Goes through the API client rather than a plain link because every /api route
 * needs the bearer token, which an <a href> can't send. The response is a blob
 * we hand to a temporary link — the same approach the SVG/draw.io exports use.
 */
export async function downloadSample(name: string): Promise<void> {
  const r = await client.get("/sample/download", {
    params: { name },
    responseType: "blob",
  });
  const url = URL.createObjectURL(r.data as Blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export async function getPalette(): Promise<PaletteResponse> {
  const r = await client.get<PaletteResponse>("/palette");
  return r.data;
}

export async function loadSample(name: string): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/sample", { name });
  return r.data;
}

export async function uploadWorkbook(file: File): Promise<DiagramResponse> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await client.post<DiagramResponse>("/upload", fd, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return r.data;
}

export async function createBlank(title?: string): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/blank", { title });
  return r.data;
}

// ---------- multi-diagram ----------
export async function listDiagrams(sessionId: string): Promise<DiagramInfo[]> {
  const r = await client.get<DiagramInfo[]>(`/diagram/${sessionId}/list`);
  return r.data;
}

export async function switchDiagram(sessionId: string, diagramId: string): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/diagram/switch", {
    session_id: sessionId,
    diagram_id: diagramId,
  });
  return r.data;
}

// ---------- node/edge mutation ----------
export async function reposition(sessionId: string, nodeId: string, x: number, y: number): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/reposition", {
    session_id: sessionId,
    node_id: nodeId,
    x,
    y,
  });
  return r.data;
}

export async function createNode(
  sessionId: string,
  entityType: string,
  opts: { label?: string; parent?: string; x?: number; y?: number } = {}
): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/node/create", {
    session_id: sessionId,
    entity_type: entityType,
    label: opts.label || "",
    parent: opts.parent || "",
    x: opts.x ?? 100,
    y: opts.y ?? 100,
  });
  return r.data;
}

export interface NodeUpdatePatch {
  label?: string;
  entity_type?: string;
  fill_override?: string;
  stroke_override?: string;
  metadata?: string;
}

export async function updateNode(sessionId: string, nodeId: string, patch: NodeUpdatePatch): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/node/update", {
    session_id: sessionId,
    node_id: nodeId,
    ...patch,
  });
  return r.data;
}

export async function deleteNode(sessionId: string, nodeId: string): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/node/delete", { session_id: sessionId, node_id: nodeId });
  return r.data;
}

export async function duplicateNode(sessionId: string, nodeId: string): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/node/duplicate", { session_id: sessionId, node_id: nodeId });
  return r.data;
}

export async function reparentNode(sessionId: string, nodeId: string, parent: string): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/node/reparent", {
    session_id: sessionId,
    node_id: nodeId,
    parent,
  });
  return r.data;
}

export async function createEdge(
  sessionId: string,
  sourceId: string,
  targetId: string,
  relationType: string,
  label = ""
): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/edge/create", {
    session_id: sessionId,
    source_id: sourceId,
    target_id: targetId,
    relation_type: relationType,
    label,
  });
  return r.data;
}

export interface EdgeUpdatePatch {
  relation_type?: string;
  label?: string;
  reverse?: boolean;
}

export async function updateEdge(sessionId: string, edgeId: string, patch: EdgeUpdatePatch): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/edge/update", {
    session_id: sessionId,
    edge_id: edgeId,
    ...patch,
  });
  return r.data;
}

export async function deleteEdge(sessionId: string, edgeId: string): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/edge/delete", { session_id: sessionId, edge_id: edgeId });
  return r.data;
}

// ---------- layout / history ----------
export async function autoArrange(sessionId: string, direction?: "TB" | "LR"): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/auto-arrange", { session_id: sessionId, direction });
  return r.data;
}

export async function undo(sessionId: string): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/undo", { session_id: sessionId });
  return r.data;
}

export async function redo(sessionId: string): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/redo", { session_id: sessionId });
  return r.data;
}

// ---------- CSV / templates / outline ----------
export async function applyCsv(
  sessionId: string,
  nodesCsv: string,
  edgesCsv = "",
  shapesCsv = "",
  linesCsv = ""
): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/csv/apply", {
    session_id: sessionId,
    nodes_csv: nodesCsv,
    edges_csv: edgesCsv,
    shapes_csv: shapesCsv,
    lines_csv: linesCsv,
  });
  return r.data;
}

export async function listTemplates(): Promise<TemplatesResponse> {
  const r = await client.get<TemplatesResponse>("/templates");
  return r.data;
}

export async function generateTemplate(templateName: string, params: Record<string, string>): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/template/generate", {
    template_name: templateName,
    params,
  });
  return r.data;
}

export async function generateOutline(text: string, entityType: string, relationType: string): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/outline/generate", {
    text,
    entity_type: entityType,
    relation_type: relationType,
  });
  return r.data;
}

// ---------- style rules ----------
export async function setStyleRules(sessionId: string, rulesText: string): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/style-rules", {
    session_id: sessionId,
    rules_text: rulesText,
  });
  return r.data;
}

// ---------- saved projects (SQLite-backed, survives restarts) ----------
export async function listProjects(): Promise<ProjectInfo[]> {
  const r = await client.get<ProjectInfo[]>("/projects");
  return r.data;
}

export async function saveProject(
  sessionId: string,
  name: string,
  projectId?: string | null
): Promise<ProjectInfo> {
  const r = await client.post<ProjectInfo>("/projects/save", {
    session_id: sessionId,
    name,
    project_id: projectId || null,
  });
  return r.data;
}

export async function loadProject(projectId: string): Promise<DiagramResponse> {
  const r = await client.post<DiagramResponse>("/projects/load", { project_id: projectId });
  return r.data;
}

export async function deleteProject(projectId: string): Promise<void> {
  await client.post("/projects/delete", { project_id: projectId });
}

// ---------- PPTX export ----------
export interface ClusterBBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ClusterOut {
  id: string;
  node_ids: string[];
  top_level_ids: string[];
  bbox: ClusterBBox;
  suggested_name: string;
}

export interface OrphanOut {
  node_id: string;
  label: string;
  bbox: ClusterBBox;
  suggested_cluster_id: string | null;
  confident: boolean;
}

export interface ClusterDetectResponse {
  clusters: ClusterOut[];
  orphans: OrphanOut[];
}

export async function detectPptxClusters(sessionId: string): Promise<ClusterDetectResponse> {
  const r = await client.post<ClusterDetectResponse>("/export/pptx/detect", { session_id: sessionId });
  return r.data;
}

export async function saveExportSettings(sessionId: string, settings: Record<string, unknown>): Promise<void> {
  await client.post("/export/settings", { session_id: sessionId, settings });
}

export interface PptxPlacement {
  image_png_base64: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface PptxTextBlock {
  text: string;
  font?: string;
  size?: number;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface PptxSlidePayload {
  slide_number: number;
  placements: PptxPlacement[];
  header?: PptxTextBlock;
  content?: PptxTextBlock;
}

export interface PptxGeneratePayload {
  filename: string;
  slide_width_in?: number;
  slide_height_in?: number;
  slides: PptxSlidePayload[];
}

/** POSTs the finished plan and saves the resulting .pptx to disk — same
 * blob-response pattern as `downloadSample`, since this is a new binary
 * endpoint rather than a string already sitting on `DiagramResponse`. */
export async function exportPptx(payload: PptxGeneratePayload): Promise<void> {
  const r = await client.post("/export/pptx/generate", payload, { responseType: "blob" });
  const url = URL.createObjectURL(r.data as Blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${payload.filename}.pptx`;
  a.click();
  URL.revokeObjectURL(url);
}
