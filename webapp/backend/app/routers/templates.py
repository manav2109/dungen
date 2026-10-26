"""Template-gallery and outline-mode generation routes."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException

from diagen.spec import Spec
from diagen.layout import layout
from diagen.templates import TEMPLATES, build_outline

from ..diagram_store import store
from ..diagram_helpers import _space_connected_nodes, _build_response
from ..schemas import DiagramResponse, TemplateRequest, OutlineRequest

router = APIRouter()


@router.get("/api/templates")
def list_templates():
    return {name: {'description': t['description'],
                    'fields': [{'key': k, 'label': lbl, 'default': d} for k, lbl, d in t['fields']]}
            for name, t in TEMPLATES.items()}


@router.post("/api/template/generate", response_model=DiagramResponse)
def template_generate(req: TemplateRequest):
    tpl = TEMPLATES.get(req.template_name)
    if tpl is None:
        raise HTTPException(404, f"No such template: {req.template_name}")
    vals = {k: req.params.get(k, default) for k, _label, default in tpl['fields']}
    built = tpl['build'](vals)
    spec = Spec.blank(use_defaults=True)
    spec.load_rows(built['nodes'], built['edges'], title=built['title'])
    d = spec.diagrams['D1']
    canvas_w, canvas_h = layout(d, spec)
    _space_connected_nodes(d)
    session = store.put(spec, 'D1', canvas_w, canvas_h)
    return _build_response(session)


@router.post("/api/outline/generate", response_model=DiagramResponse)
def outline_generate(req: OutlineRequest):
    spec = Spec.blank(use_defaults=True)
    if req.entity_type not in spec.shapes:
        raise HTTPException(400, f"Unknown entity_type: {req.entity_type}")
    if req.relation_type not in spec.lines:
        raise HTTPException(400, f"Unknown relation_type: {req.relation_type}")
    built = build_outline(req.text, req.entity_type, req.relation_type)
    spec.load_rows(built['nodes'], built['edges'], title='Outline')
    d = spec.diagrams['D1']
    canvas_w, canvas_h = layout(d, spec)
    _space_connected_nodes(d)
    session = store.put(spec, 'D1', canvas_w, canvas_h)
    return _build_response(session)
