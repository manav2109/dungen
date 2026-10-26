"""Bootstrap routes: health check, the sample-workbook gallery, the
standalone default palette, and the three ways to start a session
(load a sample / upload a workbook / start blank)."""
from __future__ import annotations
import io
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from diagen.spec import Spec
from diagen.layout import layout
from diagen.defaults import DEFAULT_SHAPES, DEFAULT_LINES

from ..diagram_store import store
from ..diagram_helpers import _first_diagram_id, _space_connected_nodes, _build_response
from ..schemas import (
    MAX_UPLOAD_BYTES, DiagramResponse, PaletteResponse, ShapeOut, LineOut,
    SampleRequest, BlankRequest, SampleInfo,
)

router = APIRouter()

SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "samples"


@router.get("/api/health")
def health():
    return {"status": "ok"}


# Opening every workbook on each request would be wasteful for a list that
# changes only when someone drops a file into samples/. Keyed by (mtime, size)
# so an edited or replaced sample re-reads itself without a restart.
_sample_meta_cache: dict[str, tuple[tuple[float, int], SampleInfo]] = {}


def _sample_info(path: Path) -> SampleInfo:
    stat = path.stat()
    key = (stat.st_mtime, stat.st_size)
    cached = _sample_meta_cache.get(path.name)
    if cached and cached[0] == key:
        return cached[1]

    info = SampleInfo(name=path.name)
    try:
        spec = Spec(str(path), use_defaults=True)
        info.diagrams = len(spec.diagrams)
        info.nodes = sum(len(d.nodes) for d in spec.diagrams.values())
        info.edges = sum(len(d.edges) for d in spec.diagrams.values())
        first = next(iter(spec.diagrams.values()), None)
        title = (first.title if first else "") or ""
        # Diagram.title defaults to the diagram id when the workbook's Diagrams
        # sheet gives no title, so "D1" means "untitled" — not a useful label.
        info.title = "" if first and title == first.id else title
    except Exception:
        # An unreadable workbook (malformed, or locked open in Excel) shouldn't
        # blank out the whole picker — list it by filename with counts left
        # unknown, and let the load attempt report the real error.
        info.diagrams = info.nodes = info.edges = None
        # Don't cache a failure: a file locked by Excel right now will read fine
        # once it's closed, and its mtime won't have changed to invalidate this.
        return info

    _sample_meta_cache[path.name] = (key, info)
    return info


@router.get("/api/samples", response_model=list[SampleInfo])
def list_samples() -> list[SampleInfo]:
    if not SAMPLES_DIR.exists():
        return []
    # Excel writes `~$name.xlsx` lock files next to an open workbook; those are
    # not samples and can't be opened, so they never belong in the picker.
    paths = sorted(p for p in SAMPLES_DIR.glob("*.xlsx") if not p.name.startswith("~$"))
    return [_sample_info(p) for p in paths]


@router.get("/api/sample/download")
def download_sample(name: str):
    """Serve a sample workbook so people can open it in Excel and see how the
    Nodes/Edges rows behind a diagram are actually written."""
    # `name` comes from the query string: resolve it and confirm it really is a
    # file directly inside samples/, so a crafted name can't walk out of it.
    candidate = (SAMPLES_DIR / name).resolve()
    try:
        inside = candidate.parent == SAMPLES_DIR.resolve()
    except OSError:
        inside = False
    if not inside or candidate.suffix.lower() != ".xlsx" or name.startswith("~$"):
        raise HTTPException(400, "Not a valid sample name")
    if not candidate.is_file():
        raise HTTPException(404, f"No such sample: {name}")
    return FileResponse(
        candidate,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=candidate.name,
    )


@router.get("/api/palette", response_model=PaletteResponse)
def palette():
    """The built-in ~40-entity/~25-relation default palette, standalone — for
    bootstrapping the shape picker / template / outline UI before any
    session exists yet. Once a session is loaded, prefer the `shapes`/`lines`
    already embedded in its DiagramResponse (defaults + that workbook's own
    custom types merged)."""
    return PaletteResponse(
        shapes=[ShapeOut(entity_type=s.entity_type, family=s.family, shape=s.shape, fill=s.fill,
                          stroke=s.stroke, auto=s.auto, default_w=s.default_w, default_h=s.default_h,
                          min_w=s.min_w, min_h=s.min_h) for s in DEFAULT_SHAPES.values()],
        lines=[LineOut(relation_type=l.relation_type, family=l.family, style=l.style, width=l.width,
                        source_end=l.source_end, target_end=l.target_end, routing=l.routing,
                        label_pos=l.label_pos, color=l.color) for l in DEFAULT_LINES.values()],
    )


@router.post("/api/sample", response_model=DiagramResponse)
def load_sample(req: SampleRequest):
    # `req.name` is attacker-controlled: resolve it and confirm it really is a
    # file directly inside samples/, the same guard `download_sample` already
    # applies — without it a crafted name (e.g. "../../../../some/file.xlsx")
    # could make the backend parse and return the contents of any .xlsx file
    # reachable on disk.
    path = (SAMPLES_DIR / req.name).resolve()
    try:
        inside = path.parent == SAMPLES_DIR.resolve()
    except OSError:
        inside = False
    if not inside or not path.exists() or path.suffix != ".xlsx":
        raise HTTPException(404, f"No such sample: {req.name}")
    spec = Spec(str(path), use_defaults=True)
    active = _first_diagram_id(spec)
    canvas_w, canvas_h = layout(spec.diagrams[active], spec)
    _space_connected_nodes(spec.diagrams[active])
    session = store.put(spec, active, canvas_w, canvas_h)
    return _build_response(session)


@router.post("/api/upload", response_model=DiagramResponse)
async def upload(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(400, "Please upload a .xlsx workbook")
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)}MB)")
    try:
        spec = Spec(io.BytesIO(raw), use_defaults=True)
    except Exception as exc:  # bad workbook shape, missing sheet, etc.
        raise HTTPException(400, f"Could not read workbook: {exc}") from exc
    active = _first_diagram_id(spec)
    try:
        canvas_w, canvas_h = layout(spec.diagrams[active], spec)
        _space_connected_nodes(spec.diagrams[active])
    except KeyError as exc:
        raise HTTPException(400, f"Layout failed: {exc}") from exc
    session = store.put(spec, active, canvas_w, canvas_h)
    return _build_response(session)


@router.post("/api/blank", response_model=DiagramResponse)
def blank(req: BlankRequest):
    """Start a fresh empty diagram (default palette only) — the entry point
    for 'just start dragging shapes' / before using a template or outline."""
    from diagen.model import Diagram
    spec = Spec.blank(use_defaults=True)
    spec.diagrams['D1'] = Diagram('D1', '', req.title or 'Untitled diagram')
    canvas_w, canvas_h = layout(spec.diagrams['D1'], spec)
    session = store.put(spec, 'D1', canvas_w, canvas_h)
    return _build_response(session)
