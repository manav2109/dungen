"""Node/edge mutation, layout, undo/redo, CSV paste, and style-rule routes —
the bulk of the interactive editor's surface. Every handler mutates the
session's live Diagram object and re-renders through `_build_response`;
see app/main.py's module docstring for why there's no second copy of this
logic on the frontend."""
from __future__ import annotations
import copy

from fastapi import APIRouter, HTTPException

from diagen.layout import _shift
from diagen.model import Node, Edge

from ..diagram_helpers import (
    _get_session, _get_node, _get_edge, _descendants, _gen_id, _relayout,
    _keep_clear_of, _keep_connections_clear, _build_response, _csv_rows,
)
from ..schemas import (
    DiagramResponse, RepositionRequest, NodeCreateRequest, NodeUpdateRequest,
    NodeIdRequest, NodeReparentRequest, EdgeCreateRequest, EdgeUpdateRequest,
    EdgeIdRequest, AutoArrangeRequest, SessionIdRequest, CsvApplyRequest,
    StyleRulesRequest,
)

router = APIRouter()


@router.post("/api/reposition", response_model=DiagramResponse)
def reposition(req: RepositionRequest):
    session = _get_session(req.session_id)
    node = _get_node(session, req.node_id)
    session.push_undo()
    dx, dy = req.x - node.x, req.y - node.y
    _shift(node, dx, dy)  # moves the node and, if it's a container, its children too
    _keep_connections_clear(session.diagram, node)
    return _build_response(session)


@router.post("/api/node/create", response_model=DiagramResponse)
def node_create(req: NodeCreateRequest):
    session = _get_session(req.session_id)
    spec, d = session.spec, session.diagram
    if req.entity_type not in spec.shapes:
        raise HTTPException(400, f"Unknown entity_type: {req.entity_type}")
    if req.parent and req.parent not in d.nodes:
        raise HTTPException(404, f"No such parent node: {req.parent}")
    session.push_undo()
    nid = _gen_id('n', set(d.nodes))
    n = Node(id=nid, diagram=session.active_id, parent=req.parent, type=req.entity_type,
             label=req.label or nid)
    from diagen import sizing
    sizing.size_node(n, spec)
    n.x, n.y = req.x, req.y
    d.nodes[nid] = n
    spec._link()
    if req.parent:
        _relayout(session)  # container needs to grow to fit its new child
    return _build_response(session)


@router.post("/api/node/update", response_model=DiagramResponse)
def node_update(req: NodeUpdateRequest):
    session = _get_session(req.session_id)
    spec, d = session.spec, session.diagram
    n = _get_node(session, req.node_id)
    if req.entity_type is not None and req.entity_type not in spec.shapes:
        raise HTTPException(400, f"Unknown entity_type: {req.entity_type}")
    session.push_undo()
    if req.label is not None:
        n.label = req.label
    if req.entity_type is not None:
        n.type = req.entity_type
    if req.fill_override is not None:
        n.fill_override = req.fill_override
    if req.stroke_override is not None:
        n.stroke_override = req.stroke_override
    if req.metadata is not None:
        n.meta = req.metadata
    from diagen import sizing
    sizing.size_node(n, spec)  # label/type changes can change size
    return _build_response(session)


@router.post("/api/node/delete", response_model=DiagramResponse)
def node_delete(req: NodeIdRequest):
    session = _get_session(req.session_id)
    d = session.diagram
    _get_node(session, req.node_id)  # 404s if missing
    session.push_undo()
    doomed = {req.node_id} | _descendants(d, req.node_id)
    for nid in doomed:
        d.nodes.pop(nid, None)
    d.edges = [e for e in d.edges if e.source not in doomed and e.target not in doomed]
    session.spec._link()
    return _build_response(session)


@router.post("/api/node/duplicate", response_model=DiagramResponse)
def node_duplicate(req: NodeIdRequest):
    session = _get_session(req.session_id)
    d = session.diagram
    n = _get_node(session, req.node_id)
    session.push_undo()
    nid = _gen_id('n', set(d.nodes))
    clone = copy.deepcopy(n)
    clone.id = nid
    clone.label = f'{n.label} copy'
    clone.x, clone.y = n.x + 24, n.y + 24
    clone.children = []
    d.nodes[nid] = clone
    session.spec._link()
    return _build_response(session)


@router.post("/api/node/reparent", response_model=DiagramResponse)
def node_reparent(req: NodeReparentRequest):
    session = _get_session(req.session_id)
    d = session.diagram
    n = _get_node(session, req.node_id)
    if req.parent and req.parent not in d.nodes:
        raise HTTPException(404, f"No such parent node: {req.parent}")
    if req.parent in ({req.node_id} | _descendants(d, req.node_id)):
        raise HTTPException(400, "Can't move a node inside itself or its own descendant")
    session.push_undo()
    n.parent = req.parent
    session.spec._link()
    _relayout(session)  # old and new parent containers both need to re-fit
    return _build_response(session)


@router.post("/api/edge/create", response_model=DiagramResponse)
def edge_create(req: EdgeCreateRequest):
    session = _get_session(req.session_id)
    spec, d = session.spec, session.diagram
    if req.source_id not in d.nodes or req.target_id not in d.nodes:
        raise HTTPException(404, "source_id/target_id must both be nodes in the active diagram")
    if req.relation_type not in spec.lines:
        raise HTTPException(400, f"Unknown relation_type: {req.relation_type}")
    session.push_undo()
    eid = _gen_id('e', {e.id for e in d.edges})
    d.edges.append(Edge(id=eid, diagram=session.active_id, source=req.source_id,
                         target=req.target_id, relation=req.relation_type, label=req.label))
    # Connecting two shapes that already happen to sit close together hits the
    # same messy dip-under route as dragging one in close — jump the target
    # clear of the source the same way reposition does.
    _keep_clear_of(d.nodes[req.target_id], d.nodes[req.source_id])
    return _build_response(session)


@router.post("/api/edge/update", response_model=DiagramResponse)
def edge_update(req: EdgeUpdateRequest):
    session = _get_session(req.session_id)
    spec = session.spec
    e = _get_edge(session, req.edge_id)
    if req.relation_type is not None and req.relation_type not in spec.lines:
        raise HTTPException(400, f"Unknown relation_type: {req.relation_type}")
    session.push_undo()
    if req.relation_type is not None:
        e.relation = req.relation_type
    if req.label is not None:
        e.label = req.label
    if req.reverse:
        e.source, e.target = e.target, e.source
    return _build_response(session)


@router.post("/api/edge/delete", response_model=DiagramResponse)
def edge_delete(req: EdgeIdRequest):
    session = _get_session(req.session_id)
    d = session.diagram
    _get_edge(session, req.edge_id)  # 404s if missing
    session.push_undo()
    d.edges = [e for e in d.edges if e.id != req.edge_id]
    return _build_response(session)


@router.post("/api/auto-arrange", response_model=DiagramResponse)
def auto_arrange(req: AutoArrangeRequest):
    session = _get_session(req.session_id)
    d = session.diagram
    session.push_undo()
    if req.direction:
        d.direction = 'left-right' if req.direction.upper() == 'LR' else 'top-down'
    for n in d.nodes.values():
        n.rank, n.order = 0, 0  # force a fresh topological pass in layout()
    _relayout(session)
    return _build_response(session)


@router.post("/api/undo", response_model=DiagramResponse)
def undo(req: SessionIdRequest):
    session = _get_session(req.session_id)
    if not session.undo():
        raise HTTPException(400, "Nothing to undo")
    return _build_response(session)


@router.post("/api/redo", response_model=DiagramResponse)
def redo(req: SessionIdRequest):
    session = _get_session(req.session_id)
    if not session.redo():
        raise HTTPException(400, "Nothing to redo")
    return _build_response(session)


@router.post("/api/csv/apply", response_model=DiagramResponse)
def csv_apply(req: CsvApplyRequest):
    """Replace the ACTIVE diagram's nodes/edges from pasted CSV text — other
    diagrams in this session are untouched. Mirrors the playground's
    'Apply CSV → canvas'. Since pasted rows carry rank/order hints rather
    than x/y, this always ends with a full layout pass."""
    session = _get_session(req.session_id)
    session.push_undo()
    unknown = session.spec.replace_diagram_data(
        session.active_id,
        node_rows=_csv_rows(req.nodes_csv),
        edge_rows=_csv_rows(req.edges_csv),
        shape_rows=_csv_rows(req.shapes_csv),
        line_rows=_csv_rows(req.lines_csv),
    )
    if not session.diagram.nodes:
        raise HTTPException(400, "No usable node rows found" +
                             (f" (unknown entity types: {', '.join(unknown)})" if unknown else ""))
    _relayout(session)
    return _build_response(session, unknown_types=unknown)


@router.post("/api/style-rules", response_model=DiagramResponse)
def style_rules(req: StyleRulesRequest):
    session = _get_session(req.session_id)
    session.style_rules = req.rules_text
    return _build_response(session)
