"""Saved-project routes (SQLite/Postgres-backed, survives restarts).

Every route here reads `request.state.user_id`, set by `auth_middleware` in
app/main.py — these paths are never in PUBLIC_API_PATHS, so it's always
present.
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request

from diagen.layout import layout

from .. import projects as project_store
from ..diagram_store import store
from ..diagram_helpers import _first_diagram_id, _space_connected_nodes, _build_response, _get_session
from ..schemas import (
    MAX_PROJECTS_PER_USER, ProjectInfo, ProjectSaveRequest, ProjectIdRequest, DiagramResponse,
)

router = APIRouter()


@router.get("/api/projects", response_model=list[ProjectInfo])
def projects_list(request: Request):
    return project_store.list_projects(request.state.user_id)


@router.post("/api/projects/save", response_model=ProjectInfo)
def projects_save(req: ProjectSaveRequest, request: Request):
    name = req.name.strip()
    if not name:
        raise HTTPException(400, "Project name can't be empty")
    user_id = request.state.user_id
    session = _get_session(req.session_id)
    if not req.project_id and project_store.count_projects(user_id) >= MAX_PROJECTS_PER_USER:
        raise HTTPException(409, f"Saved-project limit reached ({MAX_PROJECTS_PER_USER})")
    # Wrapped (not a bare spec dict) so the Export panel's settings travel
    # with the project — see Session.export_settings. "spec" key presence
    # is how projects_load tells this format apart from a pre-export-panel
    # row, which was the bare spec dict at the top level.
    data = {"spec": project_store.spec_to_dict(session.spec), "export_settings": session.export_settings}
    try:
        pid = project_store.save_project(name, data, user_id, req.project_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    row = next(p for p in project_store.list_projects(user_id) if p["id"] == pid)
    return ProjectInfo(**row)


@router.post("/api/projects/load", response_model=DiagramResponse)
def projects_load(req: ProjectIdRequest, request: Request):
    project = project_store.get_project(req.project_id, request.state.user_id)
    if project is None:
        raise HTTPException(404, f"No such project: {req.project_id}")
    try:
        raw = project["data"]
        spec_dict = raw["spec"] if isinstance(raw, dict) and "spec" in raw else raw
        spec = project_store.spec_from_dict(spec_dict)
        active = _first_diagram_id(spec)
        canvas_w, canvas_h = layout(spec.diagrams[active], spec)
        _space_connected_nodes(spec.diagrams[active])
        session = store.put(spec, active, canvas_w, canvas_h)
        if isinstance(raw, dict):
            session.export_settings = raw.get("export_settings", {})
        return _build_response(session)
    except (KeyError, ValueError) as exc:  # corrupt/old-format row, shouldn't happen but don't 500 opaquely
        raise HTTPException(400, f"Could not load project: {exc}") from exc


@router.post("/api/projects/delete")
def projects_delete(req: ProjectIdRequest, request: Request):
    deleted = project_store.delete_project(req.project_id, request.state.user_id)
    if not deleted:
        raise HTTPException(404, f"No such project: {req.project_id}")
    return {"deleted": True}
