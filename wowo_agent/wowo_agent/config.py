from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
    load_dotenv(".env.local", override=True)
except ImportError:
    pass


@dataclass(frozen=True)
class Settings:
    model: str = "gpt-5.4-mini"
    embedding_model: str = "text-embedding-3-small"
    embeddings_enabled: bool = True
    api_key: str | None = None
    base_url: str | None = None
    knowledge_dir: Path = Path("knowledge")
    skill_dir: Path = Path("skills")
    max_tool_rounds: int = 5
    openai_timeout: float = 180.0
    openai_connect_timeout: float = 20.0
    openai_max_retries: int = 1
    host: str = "127.0.0.1"
    port: int = 8000

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            model=os.getenv("OPENAI_MODEL", cls.model),
            embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", cls.embedding_model),
            embeddings_enabled=os.getenv("WOWO_EMBEDDINGS_ENABLED", "1").lower()
            not in {"0", "false", "no", "off"},
            api_key=os.getenv("ZAI_API_KEY") or os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL") or None,
            knowledge_dir=Path(os.getenv("WOWO_KNOWLEDGE_DIR", "knowledge")),
            skill_dir=Path(os.getenv("WOWO_SKILL_DIR", "skills")),
            max_tool_rounds=int(os.getenv("WOWO_MAX_TOOL_ROUNDS", "5")),
            openai_timeout=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "180")),
            openai_connect_timeout=float(os.getenv("OPENAI_CONNECT_TIMEOUT_SECONDS", "20")),
            openai_max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "1")),
            host=os.getenv("WOWO_HOST", cls.host),
            port=int(os.getenv("WOWO_PORT", str(cls.port))),
        )

    def require_api_key(self) -> None:
        if not self.api_key:
            raise RuntimeError("请先设置 ZAI_API_KEY 或 OPENAI_API_KEY 环境变量")
