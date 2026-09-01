from __future__ import annotations

import json
import re
import uuid
from html import escape
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
class CircleHole(BaseModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    diameter: float = Field(gt=0)
    label: str = ""


class RectCutout(BaseModel):
    x: float = Field(ge=0, description="左下角 X 坐标")
    y: float = Field(ge=0, description="左下角 Y 坐标")
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    label: str = ""


class CADPlan(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=2000)
    material: str = Field(min_length=1, max_length=120)
    units: Literal["mm"] = "mm"
    width: float = Field(gt=0, le=1_000_000)
    height: float = Field(gt=0, le=1_000_000)
    thickness: float = Field(gt=0, le=100_000)
    quantity: int = Field(default=1, ge=1, le=100_000)
    holes: list[CircleHole] = Field(default_factory=list, max_length=200)
    cutouts: list[RectCutout] = Field(default_factory=list, max_length=100)
    manufacturing_steps: list[str] = Field(min_length=1, max_length=30)
    notes: list[str] = Field(default_factory=list, max_length=30)

    def validate_geometry(self) -> None:
        errors: list[str] = []
        for index, hole in enumerate(self.holes, start=1):
            radius = hole.diameter / 2
            if not (radius <= hole.x <= self.width - radius):
                errors.append(f"圆孔 {index} 超出板件 X 边界")
            if not (radius <= hole.y <= self.height - radius):
                errors.append(f"圆孔 {index} 超出板件 Y 边界")
        for index, cutout in enumerate(self.cutouts, start=1):
            if cutout.x + cutout.width > self.width:
                errors.append(f"矩形开槽 {index} 超出板件 X 边界")
            if cutout.y + cutout.height > self.height:
                errors.append(f"矩形开槽 {index} 超出板件 Y 边界")
        if errors:
            raise ValueError("；".join(errors))


CAD_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "material": {"type": "string"},
        "units": {"type": "string", "enum": ["mm"]},
        "width": {"type": "number", "exclusiveMinimum": 0},
        "height": {"type": "number", "exclusiveMinimum": 0},
        "thickness": {"type": "number", "exclusiveMinimum": 0},
        "quantity": {"type": "integer", "minimum": 1},
        "holes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "x": {"type": "number", "minimum": 0},
                    "y": {"type": "number", "minimum": 0},
                    "diameter": {"type": "number", "exclusiveMinimum": 0},
                    "label": {"type": "string"},
                },
                "required": ["x", "y", "diameter", "label"],
                "additionalProperties": False,
            },
        },
        "cutouts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "x": {"type": "number", "minimum": 0},
                    "y": {"type": "number", "minimum": 0},
                    "width": {"type": "number", "exclusiveMinimum": 0},
                    "height": {"type": "number", "exclusiveMinimum": 0},
                    "label": {"type": "string"},
                },
                "required": ["x", "y", "width", "height", "label"],
                "additionalProperties": False,
            },
        },
        "manufacturing_steps": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "title",
        "summary",
        "material",
        "units",
        "width",
        "height",
        "thickness",
        "quantity",
        "holes",
        "cutouts",
        "manufacturing_steps",
        "notes",
    ],
    "additionalProperties": False,
}


class CADPlanner:
    def __init__(self, client: Any, model: str):
        self.client = client
        self.model = model

    def create_plan(self, description: str, context: list[dict[str, Any]] | None = None) -> CADPlan:
        references = "\n\n".join(
            f"来源 {item.get('source', '未知')}：\n{item.get('text', '')}"
            for item in (context or [])[:5]
        ) or "无可用知识库资料。"
        prompt = f"""根据用户需求生成可制造的二维矩形板件 CAD 方案。
当前仅支持矩形外轮廓、圆孔、矩形开槽，所有尺寸统一换算为 mm，坐标原点为板件左下角。
只使用用户明确给出的关键尺寸；不得猜测宽、高、厚度、孔径或孔位。信息不足时不要调用提交工具，直接用中文说明缺少哪些参数。
孔和开槽必须完全位于板件轮廓内。manufacturing_steps 给出具体加工顺序，notes 写公差、安全或待工程师复核项。

用户需求：
{description}

知识库参考（仅在相关时采用）：
{references}"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "你是机械制图与加工工艺助手。关键尺寸缺失时必须拒绝出图。"},
                {"role": "user", "content": prompt},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "submit_cad_plan",
                        "description": "提交已具备全部关键尺寸、可以出图的制作方案",
                        "parameters": CAD_PLAN_SCHEMA,
                    },
                }
            ],
            tool_choice="auto",
        )
        message = response.choices[0].message
        calls = message.tool_calls or []
        if not calls:
            clarification = (message.content or "").strip()
            raise ValueError(clarification or "缺少板件宽度、高度、厚度或特征尺寸，无法绘制 CAD 图")
        call = next((item for item in calls if item.function.name == "submit_cad_plan"), None)
        if call is None:
            raise ValueError("模型未返回有效的 CAD 制作方案")
        try:
            raw = json.loads(call.function.arguments)
            # Some OpenAI-compatible gateways double-encode array-valued tool
            # arguments. Decode only the known container fields before strict
            # Pydantic and geometry validation.
            for key in ("holes", "cutouts", "manufacturing_steps", "notes"):
                value = raw.get(key)
                if isinstance(value, str):
                    try:
                        raw[key] = json.loads(value)
                    except json.JSONDecodeError:
                        if key in {"manufacturing_steps", "notes"} and value.strip():
                            raw[key] = [value.strip()]
            plan = CADPlan.model_validate(raw)
            plan.validate_geometry()
            return plan
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise ValueError(f"CAD 方案参数校验失败：{exc}") from exc


def _number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def _dxf_pair(code: int, value: str | int | float) -> str:
    return f"{code}\n{value}\n"


def _dxf_line(x1: float, y1: float, x2: float, y2: float, layer: str) -> str:
    return "".join(
        _dxf_pair(code, value)
        for code, value in (
            (0, "LINE"), (8, layer), (10, _number(x1)), (20, _number(y1)),
            (30, 0), (11, _number(x2)), (21, _number(y2)), (31, 0),
        )
    )


def _dxf_rect(x: float, y: float, width: float, height: float, layer: str) -> str:
    return "".join(
        [
            _dxf_pair(0, "LWPOLYLINE"),
            _dxf_pair(8, layer),
            _dxf_pair(90, 4),
            _dxf_pair(70, 1),
            *[
                _dxf_pair(10, _number(px)) + _dxf_pair(20, _number(py))
                for px, py in ((x, y), (x + width, y), (x + width, y + height), (x, y + height))
            ],
        ]
    )


def _dxf_text(x: float, y: float, value: str, height: float, layer: str = "NOTES") -> str:
    safe = value.replace("\r", " ").replace("\n", " ")[:240]
    return "".join(
        _dxf_pair(code, item)
        for code, item in (
            (0, "TEXT"), (8, layer), (10, _number(x)), (20, _number(y)),
            (30, 0), (40, _number(height)), (1, safe),
        )
    )


def render_dxf(plan: CADPlan) -> str:
    dimension_gap = max(plan.width, plan.height) * 0.08
    text_height = max(2.5, min(plan.width, plan.height) * 0.025)
    entities = [_dxf_rect(0, 0, plan.width, plan.height, "OUTLINE")]
    for hole in plan.holes:
        entities.append(
            "".join(
                _dxf_pair(code, value)
                for code, value in (
                    (0, "CIRCLE"), (8, "CUT"), (10, _number(hole.x)),
                    (20, _number(hole.y)), (30, 0), (40, _number(hole.diameter / 2)),
                )
            )
        )
        entities.append(_dxf_text(hole.x + hole.diameter / 2, hole.y, f"D{_number(hole.diameter)}", text_height))
    for cutout in plan.cutouts:
        entities.append(_dxf_rect(cutout.x, cutout.y, cutout.width, cutout.height, "CUT"))
    entities.extend(
        [
            _dxf_line(0, plan.height + dimension_gap, plan.width, plan.height + dimension_gap, "DIMENSIONS"),
            _dxf_text(plan.width / 2, plan.height + dimension_gap + text_height, _number(plan.width), text_height, "DIMENSIONS"),
            _dxf_line(-dimension_gap, 0, -dimension_gap, plan.height, "DIMENSIONS"),
            _dxf_text(-dimension_gap - text_height * 3, plan.height / 2, _number(plan.height), text_height, "DIMENSIONS"),
            _dxf_text(0, -dimension_gap * 1.5, f"{plan.title} | {plan.material} | t={_number(plan.thickness)} mm", text_height),
        ]
    )
    return "".join(
        [
            _dxf_pair(0, "SECTION"), _dxf_pair(2, "HEADER"),
            _dxf_pair(9, "$ACADVER"), _dxf_pair(1, "AC1021"),
            _dxf_pair(9, "$INSUNITS"), _dxf_pair(70, 4),
            _dxf_pair(0, "ENDSEC"), _dxf_pair(0, "SECTION"), _dxf_pair(2, "ENTITIES"),
            *entities,
            _dxf_pair(0, "ENDSEC"), _dxf_pair(0, "EOF"),
        ]
    )


def write_dwg_file(plan: CADPlan, target: Path) -> None:
    """Write a genuine binary DWG (Autodesk R2000 / AC1015) using ezdwg.

    The binary is authored natively by ``ezdwg.raw.write_ac1015_dwg`` (no
    DXF round-trip), producing an ASCII-version header ``AC1015`` file that
    LibreDWG/AutoCAD-compatible readers can open.
    """
    from ezdwg.raw import write_ac1015_dwg

    lines: list[tuple[int, float, float, float, float, float, float]] = []
    arcs: list[tuple[int, float, float, float, float, float, float]] = []
    circles: list[tuple[int, float, float, float, float]] = []
    lwpolylines: list[
        tuple[int, int, list[tuple[float, float]], list[float], list[tuple[float, float]], float | None]
    ] = []
    texts: list[tuple[int, str, tuple[float, float, float], float, float]] = []
    mtexts: list[Any] = []

    def _handle() -> int:
        _handle.counter += 1
        return _handle.counter

    _handle.counter = 0

    # Outer outline as a closed LWPOLYLINE.
    lwpolylines.append(
        (
            _handle(),
            1,
            [(0, 0), (plan.width, 0), (plan.width, plan.height), (0, plan.height)],
            [],
            [],
            None,
        )
    )
    # Circular holes.
    for hole in plan.holes:
        circles.append((_handle(), hole.x, hole.y, 0.0, hole.diameter / 2))
    # Rectangular cutouts as closed LWPOLYLines.
    for cutout in plan.cutouts:
        lwpolylines.append(
            (
                _handle(),
                1,
                [
                    (cutout.x, cutout.y),
                    (cutout.x + cutout.width, cutout.y),
                    (cutout.x + cutout.width, cutout.y + cutout.height),
                    (cutout.x, cutout.y + cutout.height),
                ],
                [],
                [],
                None,
            )
        )

    dimension_gap = max(plan.width, plan.height) * 0.08
    text_height = max(2.5, min(plan.width, plan.height) * 0.025)
    # Horizontal width dimension line + label.
    lines.append(
        ( _handle(), 0, plan.height + dimension_gap, 0, plan.width, plan.height + dimension_gap, 0)
    )
    texts.append(
        (_handle(), _number(plan.width), (plan.width / 2, plan.height + dimension_gap + text_height, 0.0), text_height, 0.0)
    )
    # Vertical height dimension line + label.
    lines.append(
        (_handle(), -dimension_gap, 0, 0, -dimension_gap, plan.height, 0)
    )
    texts.append(
        (_handle(), _number(plan.height), (-dimension_gap - text_height * 3, plan.height / 2, 0.0), text_height, 0.0)
    )
    # Title / material note.
    texts.append(
        (
            _handle(),
            f"{plan.title} | {plan.material} | t={_number(plan.thickness)} mm",
            (0, -dimension_gap * 1.5, 0.0),
            text_height,
            0.0,
        )
    )

    write_ac1015_dwg(
        str(target),
        lines,
        arcs,
        circles,
        lwpolylines,
        texts,
        mtexts,
    )


def render_svg(plan: CADPlan) -> str:
    margin = max(plan.width, plan.height) * 0.18
    min_x, min_y = -margin, -margin
    view_width, view_height = plan.width + margin * 2, plan.height + margin * 2
    stroke = max(view_width, view_height) / 600
    font_size = max(view_width, view_height) / 45
    parts = [
        f'<rect x="0" y="0" width="{_number(plan.width)}" height="{_number(plan.height)}" class="outline"/>',
    ]
    for hole in plan.holes:
        parts.append(
            f'<circle cx="{_number(hole.x)}" cy="{_number(plan.height - hole.y)}" '
            f'r="{_number(hole.diameter / 2)}" class="cut"/>'
        )
    for cutout in plan.cutouts:
        svg_y = plan.height - cutout.y - cutout.height
        parts.append(
            f'<rect x="{_number(cutout.x)}" y="{_number(svg_y)}" width="{_number(cutout.width)}" '
            f'height="{_number(cutout.height)}" class="cut"/>'
        )
    parts.extend(
        [
            f'<line x1="0" y1="{-margin / 2}" x2="{_number(plan.width)}" y2="{-margin / 2}" class="dim"/>',
            f'<text x="{_number(plan.width / 2)}" y="{-margin / 2 - font_size / 3}" class="label">{_number(plan.width)} mm</text>',
            f'<line x1="{-margin / 2}" y1="0" x2="{-margin / 2}" y2="{_number(plan.height)}" class="dim"/>',
            f'<text x="{-margin / 2 - font_size / 2}" y="{_number(plan.height / 2)}" class="vlabel">{_number(plan.height)} mm</text>',
        ]
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{_number(min_x)} {_number(min_y)} {_number(view_width)} {_number(view_height)}">'
        f'<style>.outline{{fill:#f8fafc;stroke:#172033;stroke-width:{stroke}}}.cut{{fill:#fff;stroke:#2563eb;stroke-width:{stroke}}}'
        f'.dim{{stroke:#667085;stroke-width:{stroke * 0.7}}}.label,.vlabel{{fill:#344054;font:500 {font_size}px sans-serif;text-anchor:middle}}'
        '.vlabel{writing-mode:vertical-rl}</style>'
        + "".join(parts)
        + f'<text x="0" y="{_number(plan.height + margin * 0.65)}" style="font:600 {font_size}px sans-serif">{escape(plan.title)}</text>'
        + '</svg>'
    )


class CADArtifactStore:
    JOB_ID = re.compile(r"^[0-9a-f]{32}$")

    def __init__(self, knowledge_root: Path):
        self.root = knowledge_root / ".cad"

    def create(self, plan: CADPlan) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        target = self.root / job_id
        target.mkdir(parents=True, exist_ok=False)
        (target / "drawing.dxf").write_text(render_dxf(plan), encoding="utf-8")
        write_dwg_file(plan, target / "drawing.dwg")
        (target / "preview.svg").write_text(render_svg(plan), encoding="utf-8")
        (target / "plan.json").write_text(
            json.dumps(plan.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {
            "id": job_id,
            "dxf_url": f"/api/cad/files/{job_id}/drawing.dxf",
            "dwg_url": f"/api/cad/files/{job_id}/drawing.dwg",
            "svg_url": f"/api/cad/files/{job_id}/preview.svg",
            "plan_url": f"/api/cad/files/{job_id}/plan.json",
        }

    def resolve(self, job_id: str, filename: str) -> Path:
        allowed = {"drawing.dxf", "drawing.dwg", "preview.svg", "plan.json"}
        if not self.JOB_ID.fullmatch(job_id) or filename not in allowed:
            raise FileNotFoundError("CAD 文件不存在")
        path = self.root / job_id / filename
        if not path.is_file():
            raise FileNotFoundError("CAD 文件不存在")
        return path
