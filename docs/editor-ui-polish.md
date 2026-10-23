# DrawGen Editor UI Polish

## Purpose

Make the application easier to scan and use without changing the diagram engine,
Excel definitions, saved-project format, or SVG / draw.io / HTML rendering.

## Interface changes

- Split the crowded toolbar into a document header and an editing toolbar.
- Group upload, blank diagrams, and sample workbooks under **New / Open**.
- Group SVG, draw.io, and HTML downloads under **Export**, with format descriptions.
- Organize the sidebar into **Shapes**, **Properties**, **Create**, **Data & Styles**,
  and **Projects**. Templates, outline, voice, CSV, and style rules remain accessible.
  Existing persisted panel keys still work, including in the collapsed rail.
- Replace raw shape-name chips with accessible, draggable cards and small neutral
  library silhouettes. These thumbnails are illustrative; the Python renderer
  remains authoritative for actual diagram geometry.
- Use readable shape and connection labels while preserving the original IDs in
  API requests and workbook data. Search accepts names, IDs, and categories.
- Group properties into Basic, Appearance, Connections, and collapsed Advanced
  metadata. Show actual shape-default color swatches and distinguish overrides.
  Style-rule overlays are disclosed separately rather than misrepresented as defaults.
- Keep property drafts synchronized with server updates and undo/redo; unchanged
  fields do not trigger edits, and failed edits remain retryable.
- Add three starting choices (Upload Excel, Use a template, Blank diagram), recent
  projects, and expandable sample workbooks with their existing download actions.
- Replace the browser save prompt with a labelled, focus-trapped native dialog.
- Make connection popups optional and consolidate canvas view controls.
- Move long CSV type references into expandable help sections.
- Standardize typography, spacing, buttons, inputs, borders, focus indicators, and
  error messages. Include password fields in the shared input styling.
- Adapt the header and editing tools to smaller windows. Preserve sidebar resizing
  and add keyboard resizing (Left / Right arrows; Home resets the width).

## Verification

From the repository root:

```bash
cd webapp/frontend
npm test
npm run lint
npm run build
```

The frontend tests check rendered component contracts and presentation helpers,
not browser event handling. They use the existing React and TypeScript packages;
no new dependencies are required. Node 20.6 or newer is required for the test loader.

Run the existing backend suite separately:

```bash
cd webapp/backend
python -m pytest -q
```

The UI-only branch based on the upstream repository was checked with 9 frontend
tests and all 72 backend tests passing. The original fork also passed its 73-test
backend suite, which included the separate Excel-cleanup regression test.
The original UI browser checks used an isolated temporary database, not existing saved projects:

- Login and starting screen render without console errors.
- Shape search, creation, label editing, undo, redo, and project saving work.
- Saved projects reopen from the starting screen after a reload.
- Escape dismisses toolbar menus without losing selection and closes the save dialog.
- All creation/data tools remain accessible in the grouped sidebar.
- Collapsing and reopening the sidebar preserves the selected tool.
- The multi-diagram sample loads and its diagram switcher works.
- Layouts at 1440, 1024, and 800 pixels have no horizontal page overflow.

The export menu and callbacks are covered by component review/tests. The in-app
browser's download-event capture timed out, so file downloads still need a manual
check in a normal browser; end-to-end download verification is not claimed here.

## Scope boundary

No backend source, sample workbook, backup, renderer, or layout rule is modified.
Diagram typography, colors, and routing changes belong in a separate engine-focused
change. Existing exports and keyboard editing shortcuts remain available.
