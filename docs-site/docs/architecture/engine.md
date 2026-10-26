---
sidebar_position: 2
title: Engine
description: The diagen package's data format, module breakdown, CLI, and how to extend it with new shapes or relationships.
---

# Engine

The `diagen` package (`webapp/backend/diagen/`) generates finished diagrams
(SVG and editable draw.io XML) from plain tabular data — it's the engine
the FastAPI app wraps as a web API. It's plain local source, not a
separately pip-installed package: it lives here because the FastAPI app is
its only consumer.

Rules live in a spec workbook (`Shape_Library`/`Line_Rules` sheets, or the
~50-entity/~25-relation built-in default palette in `defaults.py`); authors
only have to provide **Nodes** and **Edges** rows.

## Data format

The part end users actually fill in:

**`Nodes`**: `diagram_id`, `node_id`, `parent_id`, `entity_type`, `label`,
`rank_hint`, `order_hint`, `w_override`, `h_override`, `fill_override`,
`stroke_override`, `metadata`

**`Edges`**: `diagram_id`, `edge_id`, `source_id`, `target_id`,
`relation_type`, `label`, `waypoint_hint`

- `parent_id` nests nodes inside containers (layers, zones, departments) —
  containers auto-size to fit their children (sizing rule SZ-08).
- `rank_hint` is the row/level, `order_hint` is the position within that
  row. That's the entire layout contract — or skip both and let edge
  topology infer them (see [Layout & Routing](/architecture/layout-and-routing)).
- ERD entities list attributes in `metadata`: `rows=id(PK);name;email`.
- `waypoint_hint` of `route:right` sends an edge around the right side
  (reject loops aside).

## Module breakdown

| Module | Responsibility |
|---|---|
| `spec.py` | Loads `Shape_Library` / `Line_Rules` / data sheets, CSVs, or in-memory rows |
| `defaults.py` | Built-in default shape/line palette |
| `sizing.py` | SZ-01..SZ-16 sizing rules: label-driven W×H, wrapping, row-list shapes |
| `layout.py` | Ranked-row placement, recursive container fit, layer-band stretching |
| `ordering.py` | Crossing reduction within each rank |
| `routing.py` | Orthogonal edge routing with obstacle avoidance |
| `render_svg.py` | 15+ shape painters, routing integration, arrowhead markers |
| `render_drawio.py` | Same model → mxGraph XML for diagrams.net |
| `interop.py` | Node/edge/connection dicts for the API layer |
| `templates.py` | Parameterized diagram generators + outline (mind-map) mode |
| `cli.py` / `__main__.py` | Standalone `python -m diagen` command line, still usable for scripting |

See [Layout & Routing](/architecture/layout-and-routing) for how `layout.py`,
`ordering.py`, and `routing.py` actually turn ranks and edges into a
readable, non-overlapping drawing.

## CLI

Useful for scripting outside the web app:

```bash
cd webapp/backend
python -m diagen tests/fixtures/Diagram_Automation_CSV_Spec.xlsx -o out
python -m diagen spec.xlsx -o out --diagram D2 --format svg
python -m diagen spec.xlsx --nodes examples/nodes.csv --edges examples/edges.csv -o out
```

Outputs: `out/<id>.svg`, `out/<id>.drawio`, and `out/index.html` gallery.

## Extending

- **New entity type** — add one row to `Shape_Library`, or to
  `defaults.py` for a built-in.
- **New relationship** — one row in `Line_Rules`, or to `defaults.py`.
- **New layout** (e.g. force-directed) — one function in `layout.py`.

## Tests

```bash
cd webapp/backend
pip install -r requirements-dev.txt
pytest
```

`tests/conftest.py` uses the real fixture workbooks in `tests/fixtures/`
and the example CSVs in `examples/` instead of hand-rolled mocks.
