from __future__ import annotations

import argparse
import sys
from dataclasses import replace

from openai import OpenAI

from .agent import Agent
from .client import create_chat_client
from .config import Settings
from .rag import LocalKnowledgeBase
from .tools import Permission, Tool, ToolRegistry


def _confirm(name: str) -> bool:
    return input(f"允许执行工具 {name}？[y/N] ").strip().lower() in {"y", "yes"}


def build_agent(settings: Settings, client: OpenAI | None = None) -> Agent:
    client = client or create_chat_client(settings)
    knowledge = LocalKnowledgeBase(
        settings.knowledge_dir,
        client=client if settings.embeddings_enabled else None,
        embedding_model=settings.embedding_model,
    )
    registry = ToolRegistry(confirm=_confirm)
    registry.register(
        Tool(
            name="retrieve_documents",
            description="从本地知识库检索与问题有关的文档片段（基于 embedding 相似度）。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索问题或关键词"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query", "limit"],
                "additionalProperties": False,
            },
            handler=knowledge.search,
            permission=Permission.ALLOW,
        )
    )
    return Agent(client, settings.model, registry, settings.max_tool_rounds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="支持工具调用和本地 RAG 的 OpenAI Agent")
    parser.add_argument("prompt", nargs="*", help="问题；留空进入交互模式")
    parser.add_argument("--model", help="覆盖 OPENAI_MODEL")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings.from_env()
    if args.model:
        settings = replace(settings, model=args.model)
    try:
        settings.require_api_key()
        agent = build_agent(settings)
        prompt = " ".join(args.prompt).strip()
        if prompt:
            print(agent.run(prompt))
            return 0
        print(f"交互模式（模型：{settings.model}，知识库：{settings.knowledge_dir}，输入 exit 退出）")
        while True:
            prompt = input("你：").strip()
            if prompt.lower() in {"exit", "quit"}:
                return 0
            if prompt:
                print(f"AI：{agent.run(prompt)}")
    except (EOFError, KeyboardInterrupt):
        print()
        return 0
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
