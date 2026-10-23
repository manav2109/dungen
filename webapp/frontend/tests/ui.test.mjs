import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { humanLabel } from "../src/uiLabels.ts";
import Toolbar from "../src/components/Toolbar.tsx";
import Palette from "../src/components/Palette.tsx";
import PropertiesPanel from "../src/components/PropertiesPanel.tsx";
import Sidebar from "../src/components/Sidebar.tsx";
import EmptyState from "../src/components/EmptyState.tsx";
import DiagramCanvas from "../src/components/DiagramCanvas.tsx";
import SaveDialog from "../src/components/SaveDialog.tsx";

const noop = () => {};
const render = (component, props) => renderToStaticMarkup(createElement(component, props));
const shape = { entity_type: "application_component", family: "EA", shape: "rounded rectangle", fill: "#abc", stroke: "#123456", auto: "", default_w: 120, default_h: 60, min_w: 40, min_h: 20 };
const node = { id: "n1", label: "Application", type: shape.entity_type, parent: "", fill_override: "", stroke_override: "", metadata: "", x: 0, y: 0, w: 120, h: 60, rank_hint: 0, order_hint: 0 };
const toolbarProps = {
  hasDiagram: true, title: "A diagram", loading: false, busy: false, error: null, onDismissError: noop,
  source: null, sourceSample: null, nodeCount: 1, edgeCount: 0, diagrams: [], activeDiagramId: "main", direction: "top-down",
  tool: "select", search: "", onUpload: noop, onSample: noop, onBlank: noop, onSwitchDiagram: noop, onSetDirection: noop,
  onAutoArrange: noop, onUndo: noop, onRedo: noop, onSetTool: noop, onSearchChange: noop, onDownload: noop,
  hasSavedProject: false, onQuickSave: noop, lastSavedAt: null, dirty: false, username: "tester", onLogout: noop,
};
const propertiesProps = {
  nodes: [node], edges: [], shapes: [shape], lines: [], connections: {}, selectedNodeIds: [node.id], selectedEdgeId: null,
  onSelectNode: noop, onUpdateNode: noop, onDeleteNode: noop, onDuplicateNode: noop, onReparentNode: noop,
  onBulkDeleteNodes: noop, onUpdateEdge: noop, onDeleteEdge: noop,
};

test("readable labels do not change the stored identifiers", () => {
  assert.equal(humanLabel("application_component"), "Application component");
  assert.equal(humanLabel("data_io"), "Data input / output");
  assert.equal(humanLabel("EA"), "Enterprise architecture");
  assert.equal(humanLabel("custom-shape"), "Custom shape");
  assert.equal(humanLabel(""), "Other");
});

test("palette cards are accessible draggable buttons with original IDs", () => {
  const html = render(Palette, { shapes: [shape], onCreate: noop });
  assert.match(html, /<button[^>]*draggable="true"[^>]*title="application_component"/);
  assert.match(html, /aria-label="Add Application component \(application_component\)"/);
  assert.match(html, /Enterprise architecture/);
  assert.match(html, /<details[^>]*open=""/);
});

test("properties preserve API values and show inherited colors", () => {
  const html = render(PropertiesPanel, propertiesProps);
  assert.match(html, /value="application_component" selected=""/);
  assert.match(html, /type="color"[^>]*value="#aabbcc"/);
  assert.match(html, /type="color"[^>]*value="#123456"/);
  assert.match(html, /Shape default/);
  assert.match(html, /<details[^>]*class="advanced-settings panel-section"/);
  assert.doesNotMatch(html, /<details[^>]*open=/);
  assert.match(html, /<footer class="panel-footer">.*Delete shape/);
});

test("properties show the stored overrides instead of defaults", () => {
  const html = render(PropertiesPanel, { ...propertiesProps, nodes: [{ ...node, fill_override: "#445566" }] });
  assert.match(html, /type="color"[^>]*value="#445566"/);
  assert.match(html, /Override/);
});

test("toolbar separates editing and file actions, with clear save and error states", () => {
  const html = render(Toolbar, { ...toolbarProps, error: "Please try again", dirty: true });
  assert.match(html, /<header class="topbar">/);
  assert.match(html, /class="editor-toolbar"/);
  assert.match(html, /New \/ Open/);
  assert.match(html, /Editable diagram/);
  assert.match(html, /Unsaved changes/);
  assert.match(html, /role="alert"/);
  assert.doesNotMatch(html, /local database/);
  const busy = render(Toolbar, { ...toolbarProps, busy: true });
  assert.match(busy, /aria-label="Undo"[^>]*disabled=""|disabled=""[^>]*aria-label="Undo"/);
});

test("grouped sidebar keeps legacy CSV and style tabs accessible", () => {
  const tabs = [["csv", "CSV", null], ["style", "Style rules", null], ["palette", "Shapes", null]];
  const props = { tabs, groups: [{ label: "Shapes", keys: ["palette"] }, { label: "Data & Styles", keys: ["csv", "style"] }], tab: "style", width: 340, onTabChange: noop, onWidthChange: noop, collapsed: false, onSetCollapsed: noop, children: "Style content" };
  const html = render(Sidebar, props);
  assert.match(html, /aria-label="Workspace panels"/);
  assert.match(html, /aria-label="Panel tools"/);
  assert.match(html, /Style rules/);
  assert.match(html, /role="separator" tabindex="0"/);
  const collapsed = render(Sidebar, { ...props, collapsed: true });
  assert.equal((collapsed.match(/class="rail-tab/g) || []).length, 2);
  assert.match(collapsed, /aria-label="Data &amp; Styles" aria-pressed="true"/);
});

test("starting screen shows creation choices and four most recent projects", () => {
  const projects = Array.from({ length: 6 }, (_, i) => ({ id: String(i), name: `Project ${i}`, updated_at: i, created_at: i }));
  const html = render(EmptyState, { onBlank: noop, onSample: noop, onUpload: noop, onGenerateTemplate: noop, onGenerateOutline: noop, onLoadProject: noop, projects });
  assert.match(html, /Upload Excel/);
  assert.match(html, /Use a template/);
  assert.match(html, /Blank diagram/);
  assert.match(html, /Open project Project 5/);
  assert.doesNotMatch(html, /Open project Project 1/);
  assert.equal((html.match(/aria-label="Open project/g) || []).length, 4);
});

test("canvas controls are labelled and connections do not pop up automatically", () => {
  const html = render(DiagramCanvas, { svg: "", nodes: [node], edges: [], connections: {}, selectedNodeIds: [node.id], selectedEdgeId: null, tool: "select", search: "", onSelectNode: noop, onSelectEdge: noop, onDragEnd: noop, onConnectCreate: noop, onDropCreate: noop, busy: true });
  assert.match(html, /aria-label="Canvas view controls"/);
  assert.match(html, /aria-label="Zoom in"/);
  assert.match(html, /aria-pressed="false"/);
  assert.doesNotMatch(html, /class="node-tooltip"/);
  assert.match(html, /role="status">Updating diagram/);
});

test("save dialog has an accessible title and rejects whitespace-only names", () => {
  const html = render(SaveDialog, { initialName: "   ", onSave: noop, onClose: noop });
  assert.match(html, /<dialog[^>]*aria-labelledby="save-dialog-title"/);
  assert.match(html, /maxlength="200" required=""/i);
  assert.match(html, /type="button" class="btn">Cancel/);
  assert.match(html, /type="submit" class="btn btn-primary" disabled="">Save diagram/);
});
