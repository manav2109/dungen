"""Multi-diagram routes: list the diagrams in the active workbook/session,
switch which one is active."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException

from ..diagram_helpers import _get_session, _relayout, _build_response
from ..schemas import DiagramInfo, DiagramResponse, DiagramSwitchRequest

router = APIRouter()


@router.get("/api/diagram/{session_id}/list", response_model=list[DiagramInfo])
def diagram_list(session_id: str):
    session = _get_session(session_id)
    return [DiagramInfo(**di) for di in session.diagram_list()]


@router.post("/api/diagram/switch", response_model=DiagramResponse)
def diagram_switch(req: DiagramSwitchRequest):
    session = _get_session(req.session_id)
    if req.diagram_id not in session.spec.diagrams:
        raise HTTPException(404, f"No such diagram: {req.diagram_id}")
    session.active_id = req.diagram_id
    _relayout(session)
    return _build_response(session)
