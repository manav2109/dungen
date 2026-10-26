"""In-memory session store: one entry per uploaded/loaded workbook.

Keeps the whole point of the "100% Python engine" decision honest: a session
holds the live diagen Spec (ALL of its diagrams, not just one) + which
diagram_id is currently active. Every mutating endpoint acts on that same
live Diagram object and re-renders through the exact same renderer used for
the initial render — there is no second, JS-side copy of layout, routing, or
diagram-editing logic anywhere in this project.

Undo/redo is a plain deep-copy snapshot stack of (nodes, edges) per diagram,
scoped per session — mirrors the JS playground's own full-state-snapshot
undo model (not a replay log), and switching the active diagram doesn't
disturb the other diagrams' history.
"""
from __future__ import annotations
import copy
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from diagen.model import Diagram
from diagen.spec import Spec

MAX_UNDO = 60


@dataclass
class Session:
    session_id: str
    spec: Spec
    active_id: str
    canvas_w: float
    canvas_h: float
    style_rules: str = ''
    # Opaque to the backend — the frontend's Export panel owns this shape
    # entirely (slide assignments, sizes, positions, orphan resolutions).
    # Round-trips through project save/load (see app/main.py's
    # projects_save/projects_load) so re-exporting an edited project
    # doesn't mean redoing the whole form.
    export_settings: dict = field(default_factory=dict)
    undo_stacks: dict = field(default_factory=dict)   # diagram_id -> [(nodes, edges), ...]
    redo_stacks: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)

    @property
    def diagram(self) -> Diagram:
        return self.spec.diagrams[self.active_id]

    def diagram_list(self) -> list[dict]:
        return [{'id': did, 'title': d.title, 'node_count': len(d.nodes)}
                for did, d in self.spec.diagrams.items()]

    # -- undo/redo, scoped to whichever diagram is active right now --------
    def push_undo(self):
        d = self.diagram
        stack = self.undo_stacks.setdefault(self.active_id, [])
        stack.append((copy.deepcopy(d.nodes), copy.deepcopy(d.edges)))
        if len(stack) > MAX_UNDO:
            del stack[0]
        self.redo_stacks[self.active_id] = []

    def undo(self) -> bool:
        stack = self.undo_stacks.get(self.active_id) or []
        if not stack:
            return False
        d = self.diagram
        self.redo_stacks.setdefault(self.active_id, []).append(
            (copy.deepcopy(d.nodes), copy.deepcopy(d.edges)))
        d.nodes, d.edges = stack.pop()
        self.spec._link()
        return True

    def redo(self) -> bool:
        stack = self.redo_stacks.get(self.active_id) or []
        if not stack:
            return False
        d = self.diagram
        self.undo_stacks.setdefault(self.active_id, []).append(
            (copy.deepcopy(d.nodes), copy.deepcopy(d.edges)))
        d.nodes, d.edges = stack.pop()
        self.spec._link()
        return True


class DiagramStore:
    """Simple TTL'd in-memory map. Fine for a local/dev tool; swap for Redis
    if this ever needs to survive a backend restart or run multi-process."""

    def __init__(self, ttl_seconds: int = 3600):
        self._sessions: dict[str, Session] = {}
        self.ttl_seconds = ttl_seconds

    def put(self, spec: Spec, active_id: str, canvas_w: float, canvas_h: float) -> Session:
        self._gc()
        sid = uuid.uuid4().hex
        session = Session(sid, spec, active_id, canvas_w, canvas_h)
        self._sessions[sid] = session
        return session

    def get(self, session_id: str) -> Optional[Session]:
        self._gc()
        session = self._sessions.get(session_id)
        if session is not None:
            session.last_active = time.time()
        return session

    def _gc(self):
        cutoff = time.time() - self.ttl_seconds
        stale = [sid for sid, s in self._sessions.items() if s.last_active < cutoff]
        for sid in stale:
            self._sessions.pop(sid, None)


store = DiagramStore()
