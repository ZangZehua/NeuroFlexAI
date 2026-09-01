from __future__ import annotations

import json
from typing import Any

from .tools import ToolRegistry


class Agent:
    def __init__(
        self,
        client: Any,
        model: str,
        tools: ToolRegistry,
        max_tool_rounds: int = 5,
        skill_instruction: str | None = None,
    ):
        self.client = client
        self.model = model
        self.tools = tools
        self.max_tool_rounds = max_tool_rounds
        instructions = (
            "你是一个可靠的中文助手。知识库相关问题优先调用 retrieve_documents；"
            "基于检索结果回答时明确列出来源，资料不足时如实说明。"
            "不要为了讨好用户而附和其倾向；对没有把握或缺乏依据的结论要明确标注不确定性，"
            "宁可缩小结论范围也不要自信地臆测（规避瞎说）。"
        )
        if skill_instruction:
            instructions += f"\n必须遵循当前 Skill 指令：\n{skill_instruction}"
        self.messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": instructions,
            }
        ]
        self.last_tool_outputs: dict[str, Any] = {}

    def run(self, prompt: str) -> str:
        self.last_tool_outputs = {}
        self.messages.append({"role": "user", "content": prompt})

        for _ in range(self.max_tool_rounds + 1):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=self.tools.chat_schemas(),
            )
            message = response.choices[0].message
            calls = message.tool_calls or []
            if not calls:
                answer = message.content or ""
                self.messages.append({"role": "assistant", "content": answer})
                return answer

            self.messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                        for call in calls
                    ],
                }
            )
            for call in calls:
                name = call.function.name
                output = self.tools.execute(name, call.function.arguments)
                try:
                    self.last_tool_outputs[name] = json.loads(output)
                except (TypeError, json.JSONDecodeError):
                    self.last_tool_outputs[name] = output
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": output,
                    }
                )
        raise RuntimeError("工具调用次数超过限制")
