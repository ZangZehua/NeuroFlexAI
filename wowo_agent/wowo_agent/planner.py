"""Solution generation with self-reflection and uncertainty.

Implements two capabilities for the AI 方案工作台:

* ``SolutionPlanner.plan`` (TODO 5): generate several *distinct* solution
  approaches (differing in strategy, not merely parameter values), each with
  explicit pros/cons, then run a reflection pass that critiques the options
  and produces a recommendation that does not simply echo the user's
  preference (anti-sycophancy).

* ``Reflector.reflect_answer`` (TODO 4): after drafting an answer, self-iterate
  and estimate an uncertainty/confidence score grounded in the retrieved
  sources, so the assistant hedges or revises instead of confidently
  fabricating (幻觉/瞎说).
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError


class SolutionOption(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    approach: str = Field(min_length=1, max_length=3000, description="方案的核心思路与实施步骤")
    advantages: list[str] = Field(default_factory=list, max_length=20, description="优点")
    disadvantages: list[str] = Field(default_factory=list, max_length=20, description="缺点/风险")
    applicable_scenarios: str = Field(default="", max_length=1000, description="适用场景")

    def differs_in_strategy(self, other: "SolutionOption") -> bool:
        """Approaches must differ in strategy, not just parameter values."""
        return self.approach.strip().casefold() != other.approach.strip().casefold()


class PlanBundle(BaseModel):
    options: list[SolutionOption] = Field(min_length=1, max_length=6)
    recommendation: str = Field(min_length=1, max_length=3000)


class Reflection(BaseModel):
    confidence: float = Field(ge=0.0, le=1.0, description="0~1 的置信度/确定性")
    grounded: bool = Field(description="回答是否主要基于检索到的资料")
    gaps: list[str] = Field(default_factory=list, max_length=20, description="不确定之处或缺失信息")
    self_critique: str = Field(default="", max_length=2000, description="对草稿的自我批判与修正")
    revised_answer: str = Field(default="", max_length=6000, description="修正后的最终回答")
    iterations: int = Field(default=1, ge=1, le=5)


_SOLUTIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "options": {
            "type": "array",
            "minItems": 2,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "approach": {"type": "string"},
                    "advantages": {"type": "array", "items": {"type": "string"}},
                    "disadvantages": {"type": "array", "items": {"type": "string"}},
                    "applicable_scenarios": {"type": "string"},
                },
                "required": ["title", "approach", "advantages", "disadvantages"],
                "additionalProperties": False,
            },
        },
        "recommendation": {"type": "string"},
    },
    "required": ["options", "recommendation"],
    "additionalProperties": False,
}

_REFLECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "grounded": {"type": "boolean"},
        "gaps": {"type": "array", "items": {"type": "string"}},
        "self_critique": {"type": "string"},
        "revised_answer": {"type": "string"},
    },
    "required": ["confidence", "grounded", "gaps", "self_critique", "revised_answer"],
    "additionalProperties": False,
}


def _tool_call_content(message: Any) -> str:
    """Return the first tool-call's JSON arguments as a dict."""
    calls = message.tool_calls or []
    for call in calls:
        return call.function.arguments
    return message.content or ""


def _call_structured(client: Any, model: str, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Call the model with a submit-tool schema and return validated JSON dict."""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "submit",
                    "description": "提交结构化结果",
                    "parameters": schema,
                },
            }
        ],
        tool_choice="auto",
    )
    raw = _tool_call_content(response.choices[0].message)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"模型返回无法解析的结构化结果：{exc}") from exc
    return data


def _render_context(context: list[dict[str, Any]], limit: int = 6) -> str:
    if not context:
        return "无可用知识库资料。"
    return "\n\n".join(
        f"来源 {item.get('source', '未知')}：\n{item.get('text', '')}" for item in context[:limit]
    )


class SolutionPlanner:
    """Generate multiple distinct solutions with pros/cons and a reflection pass."""

    def __init__(self, client: Any, model: str, num_options: int = 3):
        self.client = client
        self.model = model
        self.num_options = num_options

    def plan(self, question: str, context: list[dict[str, Any]] | None = None) -> PlanBundle:
        references = _render_context(context or [])
        system = (
            "你是严谨的工程/科研方案设计助手。生成多种解决方案时必须满足："
            "方案之间应在思路或技术路线上有本质区别；仅改变参数数值（如尺寸、数量、材料牌号）不算多个方案。"
            "每个方案都要客观列出优缺点与适用场景，不得为了讨好用户而只推荐用户倾向的方案。"
        )
        user = (
            f"用户需求：\n{question}\n\n知识库参考（仅在相关时采用）：\n{references}\n\n"
            f"请给出 {self.num_options} 个在技术思路上明显不同的方案，并为每个方案列出优点、缺点和适用场景，"
            "再给出基于客观比较的推荐意见。"
        )
        data = _call_structured(self.client, self.model, system, user, _SOLUTIONS_SCHEMA)
        options = [SolutionOption.model_validate(item) for item in data.get("options", [])]
        if len({opt.approach.strip().casefold() for opt in options}) < 2 and len(options) > 1:
            raise ValueError("生成的方案在思路上未真正区分，请补充关键尺寸或技术路线差异后重试")
        return PlanBundle(options=options, recommendation=data.get("recommendation", ""))


class Reflector:
    """Self-iterate an answer and estimate its uncertainty (TODO 4)."""

    def __init__(self, client: Any, model: str, max_iterations: int = 2):
        self.client = client
        self.model = model
        self.max_iterations = max_iterations

    def reflect_answer(
        self,
        question: str,
        draft: str,
        context: list[dict[str, Any]] | None = None,
    ) -> Reflection:
        references = _render_context(context or [])
        system = (
            "你负责对草稿回答进行自我批判与不确定性评估，规避“很自信地瞎说”。"
            "若回答没有充分依据，就降低置信度、明确列出不确定性，并给出修正后的、更谨慎的回答；"
            "不要为了让用户满意而强行维持原结论。confidence 表示对最终回答的置信度（0~1）。"
            "grounded 表示最终回答是否主要基于检索到的资料。"
        )
        user = (
            f"问题：{question}\n\n检索到的资料：\n{references}\n\n草稿回答：\n{draft}\n\n"
            f"请自我批判草稿，指出不确定或没有依据的部分，给出修正后的最终回答与置信度。"
        )
        data = _call_structured(self.client, self.model, system, user, _REFLECTION_SCHEMA)
        reflection = Reflection.model_validate(data)
        reflection.iterations = 1
        # Self-iteration: if confidence is low, ask once more to tighten the answer.
        for _ in range(1, self.max_iterations):
            if reflection.confidence >= 0.5:
                break
            iteration_system = (
                "上一轮修正后置信度仍较低。请再次收紧回答：只保留有依据的结论，"
                "明确标注不确定的部分，必要时缩小结论范围，并更新置信度。"
            )
            iteration_user = (
                f"问题：{question}\n\n检索资料：\n{references}\n\n当前回答：\n{reflection.revised_answer}\n\n"
                f"请按以上要求再次自我批判并修正。"
            )
            data = _call_structured(self.client, self.model, iteration_system, iteration_user, _REFLECTION_SCHEMA)
            try:
                reflection = Reflection.model_validate(data)
            except ValidationError:
                break
            reflection.iterations = min(self.max_iterations, reflection.iterations + 1)
        return reflection
