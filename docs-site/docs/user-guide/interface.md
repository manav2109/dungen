---
sidebar_position: 1
title: Interface Guide
description: A tour of the editor's toolbar, sidebar panels, and dialogs.
---

# Interface Guide

A tour of the editor's layout. None of this changes the diagram engine,
workbook formats, or saved-project format — it's purely how the same
capabilities are organized and presented.

## Header and toolbar

The toolbar is split into a document header (project name, save state) and
a separate editing toolbar, rather than one crowded strip. Within the
toolbar:

- **New / Open** groups uploading a workbook, starting a blank diagram, and
  loading a sample workbook.
- **Export** groups the SVG, draw.io, and HTML downloads, each with a short
  description of what the format is for.

Both the header and the editing tools adapt to smaller windows.

## Sidebar panels

The sidebar is organized into five panels: **Shapes**, **Properties**,
**Create**, **Data & Styles**, and **Projects**. Templates, outline mode,
voice input, CSV editing, and style rules all stay reachable from here.
Existing persisted panel keys continue to work, including while the
sidebar is collapsed to its icon rail.

Sidebar width is resizable by drag, and also by keyboard once focused: Left
and Right arrows resize, Home resets to the default width. Collapsing and
reopening the sidebar preserves whichever tool was selected.

### Shapes

Shape and connection chips use readable labels instead of raw internal
names, with small neutral library silhouettes as drag handles. These
thumbnails are illustrative only — the Python layout engine is always the
source of truth for actual diagram geometry, never the chip art. Search
matches on name, ID, or category.

### Properties

Properties are grouped into **Basic**, **Appearance**, **Connections**, and
a collapsed **Advanced** section for raw metadata. Color swatches show the
shape's actual default colors and visually distinguish an override from a
default. Style-rule overlays (transient, display-only) are shown as
overlays, not misrepresented as the shape's real default styling.

Property edits stay synchronized with server updates and undo/redo:
unchanged fields never trigger a spurious edit, and a failed edit remains
retryable rather than silently dropped.

### Create

Three starting choices live here: upload an Excel workbook, generate from a
template, or start a blank diagram — alongside recent projects and
expandable sample workbooks with their existing download actions.

### Data & Styles

CSV editing uses proper multi-line text areas with clearer section
structure, rather than reading like a raw developer tool. Long CSV
column-type references are tucked into expandable help sections instead of
taking up permanent space.

### Projects

Saving uses a labelled, focus-trapped dialog in place of the browser's
native save prompt. The empty "no saved projects" state uses the same
treatment as the Properties panel's empty state, rather than a bare line of
text.

## Canvas and connections

Connection popups on the canvas are optional, and the various canvas view
controls are consolidated rather than scattered. Typography, spacing,
buttons, inputs, borders, focus indicators, and error messages — including
password fields — follow one shared style throughout, instead of varying
panel to panel.

## Keyboard and accessibility

Existing keyboard shortcuts (`V` select, `C` connect, `Ctrl+Z`/`Ctrl+Shift+Z`
undo/redo, `Delete`) remain available and are now documented in the UI
itself rather than only known to people who already knew. `Escape` dismisses
toolbar menus without losing the current selection, and closes the save
dialog. Accessibility attributes (`aria-*`, `:focus-visible`,
`prefers-reduced-motion`) carry through to every reworked component.

## Known limitation

End-to-end file-download verification (SVG/draw.io/HTML export) needs a
manual check in a normal browser — the in-app browser used during
development timed out capturing the download event, so that path is
exercised by component-level tests and manual spot checks rather than an
automated download assertion.
