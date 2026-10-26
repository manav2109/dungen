"""Pydantic request/response models for the FastAPI app.

Single source for every route's schema — routers import from here instead of
each other, so there's one place to look when a shape changes.
"""
from __future__ import annotations
from typing import Optional

from pydantic import BaseModel, Field

MAX_UPLOAD_BYTES = 15 * 1024 * 1024   # .xlsx workbooks; generous, catches abuse not real files
MAX_CSV_BYTES = 5 * 1024 * 1024       # per CSV-paste field
MAX_PROJECT_NAME_LEN = 200
MAX_PROJECTS_PER_USER = 500


# ---------- diagram payload ----------
class NodeOut(BaseModel):
    id: str
    label: str
    type: str
    x: float
    y: float
    w: float
    h: float
    parent: Optional[str] = None
    rank_hint: int = 0
    order_hint: int = 0
    w_override: Optional[float] = None
    h_override: Optional[float] = None
    fill_override: str = ''
    stroke_override: str = ''
    metadata: str = ''


class EdgeOut(BaseModel):
    id: str
    source: str
    target: str
    label: str
    relation: str
    waypoint_hint: str = ''
    source_port: str = ''
    target_port: str = ''


class ConnectionOut(BaseModel):
    edge_id: str
    other_id: str
    other_label: str
    label: str
    dir: str


class DiagramInfo(BaseModel):
    id: str
    title: str
    node_count: int


class ShapeOut(BaseModel):
    entity_type: str
    family: str
    shape: str
    fill: str
    stroke: str
    auto: str
    default_w: float
    default_h: float
    min_w: float
    min_h: float


class LineOut(BaseModel):
    relation_type: str
    family: str
    style: str
    width: float
    source_end: str
    target_end: str
    routing: str
    label_pos: str
    color: str


class DiagramResponse(BaseModel):
    session_id: str
    diagram_id: str
    title: str
    direction: str
    svg: str
    drawio: str
    html: str
    canvas_w: float
    canvas_h: float
    nodes: list[NodeOut]
    edges: list[EdgeOut]
    connections: dict[str, list[ConnectionOut]]
    diagrams: list[DiagramInfo]
    shapes: list[ShapeOut]
    lines: list[LineOut]
    style_rules: str
    unknown_types: list[str] = []
    export_settings: dict = {}


class PaletteResponse(BaseModel):
    shapes: list[ShapeOut]
    lines: list[LineOut]


class SampleInfo(BaseModel):
    name: str
    title: str = ""
    # None (not 0) when the workbook couldn't be read — e.g. it's open in Excel,
    # which locks the file. "0 shapes" would be a lie; "unknown" is the truth.
    diagrams: Optional[int] = None
    nodes: Optional[int] = None
    edges: Optional[int] = None


# ---------- requests: bootstrap / load ----------
class SampleRequest(BaseModel):
    name: str


class BlankRequest(BaseModel):
    title: Optional[str] = None


# ---------- requests: multi-diagram ----------
class DiagramSwitchRequest(BaseModel):
    session_id: str
    diagram_id: str


# ---------- requests: node/edge mutation ----------
class RepositionRequest(BaseModel):
    session_id: str
    node_id: str
    x: float
    y: float


class NodeCreateRequest(BaseModel):
    session_id: str
    entity_type: str
    label: str = ''
    parent: str = ''
    x: float = 100
    y: float = 100


class NodeUpdateRequest(BaseModel):
    session_id: str
    node_id: str
    label: Optional[str] = None
    entity_type: Optional[str] = None
    fill_override: Optional[str] = None
    stroke_override: Optional[str] = None
    metadata: Optional[str] = None


class NodeIdRequest(BaseModel):
    session_id: str
    node_id: str


class NodeReparentRequest(BaseModel):
    session_id: str
    node_id: str
    parent: str = ''


class EdgeCreateRequest(BaseModel):
    session_id: str
    source_id: str
    target_id: str
    relation_type: str
    label: str = ''


class EdgeUpdateRequest(BaseModel):
    session_id: str
    edge_id: str
    relation_type: Optional[str] = None
    label: Optional[str] = None
    reverse: bool = False


class EdgeIdRequest(BaseModel):
    session_id: str
    edge_id: str


class AutoArrangeRequest(BaseModel):
    session_id: str
    direction: Optional[str] = None  # 'TB' | 'LR'


class SessionIdRequest(BaseModel):
    session_id: str


class CsvApplyRequest(BaseModel):
    session_id: str
    nodes_csv: str = Field(max_length=MAX_CSV_BYTES)
    edges_csv: str = Field('', max_length=MAX_CSV_BYTES)
    shapes_csv: str = Field('', max_length=MAX_CSV_BYTES)
    lines_csv: str = Field('', max_length=MAX_CSV_BYTES)


class StyleRulesRequest(BaseModel):
    session_id: str
    rules_text: str


# ---------- requests: templates / outline ----------
class TemplateRequest(BaseModel):
    template_name: str
    params: dict[str, str] = {}


class OutlineRequest(BaseModel):
    text: str
    entity_type: str = 'business_actor'
    relation_type: str = 'association'


# ---------- requests/responses: saved projects ----------
class ProjectInfo(BaseModel):
    id: str
    name: str
    created_at: float
    updated_at: float


class ProjectSaveRequest(BaseModel):
    session_id: str
    name: str = Field(min_length=1, max_length=MAX_PROJECT_NAME_LEN)
    project_id: Optional[str] = None


class ProjectIdRequest(BaseModel):
    project_id: str


# ---------- PPTX export ----------
class ClusterOut(BaseModel):
    id: str
    node_ids: list[str]
    top_level_ids: list[str]
    bbox: dict[str, float]
    suggested_name: str


class OrphanOut(BaseModel):
    node_id: str
    label: str
    bbox: dict[str, float]
    suggested_cluster_id: Optional[str] = None
    confident: bool


class ClusterDetectResponse(BaseModel):
    clusters: list[ClusterOut]
    orphans: list[OrphanOut]


class PptxPlacement(BaseModel):
    # Base64-inflated bound on a ~15MB PNG — matches MAX_UPLOAD_BYTES's
    # rationale (catches abuse, not real images from this app's own canvas).
    image_png_base64: str = Field(max_length=25_000_000)
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    w: float = Field(gt=0)
    h: float = Field(gt=0)


class PptxTextBlock(BaseModel):
    text: str = Field(max_length=4000)
    font: str = 'Calibri'
    size: float = Field(default=18.0, gt=0, le=200)
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    w: float = Field(gt=0)
    h: float = Field(gt=0)


class PptxSlide(BaseModel):
    slide_number: int = Field(ge=1, le=500)
    placements: list[PptxPlacement] = Field(min_length=1, max_length=20)
    header: Optional[PptxTextBlock] = None
    content: Optional[PptxTextBlock] = None


class PptxGenerateRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    slide_width_in: float = Field(default=13.333, gt=1, le=56)
    slide_height_in: float = Field(default=7.5, gt=1, le=56)
    slides: list[PptxSlide] = Field(min_length=1, max_length=500)


class ExportSettingsRequest(BaseModel):
    session_id: str
    settings: dict


# ---------- auth ----------
class SignupRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    token: str
    username: str


class MeResponse(BaseModel):
    username: str
