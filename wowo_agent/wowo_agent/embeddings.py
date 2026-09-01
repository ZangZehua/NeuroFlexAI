from __future__ import annotations

import hashlib
import json
import math
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .documents import SUPPORTED_SUFFIXES, chunk_text, extract_text


@dataclass
class StoredChunk:
    id: str
    source: str
    text: str
    embedding: list[float]
    mtime: float
    size: int


class EmbeddingStore:
    """Persistent OpenAI-embedding vector store for local RAG."""

    def __init__(
        self,
        root: Path,
        client: Any | None = None,
        model: str = "text-embedding-3-small",
        chunk_size: int = 800,
        overlap: int = 120,
    ):
        self.root = root.resolve()
        self.client = client
        self.model = model
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.index_path = self.root / ".rag_index.json"
        self._lock = threading.Lock()
        self._chunks: list[StoredChunk] = []
        self._load()

    def _require_client(self) -> Any:
        if self.client is None:
            raise RuntimeError("未配置 OpenAI client，无法生成 embedding")
        return self.client

    def _load(self) -> None:
        if not self.index_path.exists():
            self._chunks = []
            return
        data = json.loads(self.index_path.read_text(encoding="utf-8"))
        if data.get("model") != self.model:
            self._chunks = []
            return
        self._chunks = [StoredChunk(**item) for item in data.get("chunks", [])]

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": self.model,
            "chunks": [asdict(chunk) for chunk in self._chunks],
        }
        self.index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _chunk_id(source: str, text: str) -> str:
        digest = hashlib.sha256(f"{source}\n{text}".encode("utf-8")).hexdigest()[:24]
        return f"{source}:{digest}"

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        client = self._require_client()
        vectors: list[list[float]] = []
        batch_size = 64
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            response = client.embeddings.create(model=self.model, input=batch)
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors.extend(item.embedding for item in ordered)
        return vectors

    def list_documents(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        docs: list[dict[str, Any]] = []
        indexed = {chunk.source for chunk in self._chunks}
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(self.root)
            if any(part.startswith(".") for part in relative.parts):
                continue
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            rel = relative.as_posix()
            docs.append(
                {
                    "name": rel,
                    "size": path.stat().st_size,
                    "suffix": path.suffix.lower(),
                    "indexed": rel in indexed,
                    "chunks": sum(1 for chunk in self._chunks if chunk.source == rel),
                }
            )
        return docs

    def ingest_file(self, path: Path) -> dict[str, Any]:
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(str(path))
        if self.root not in path.parents and path.parent != self.root:
            raise ValueError("文件必须位于知识库目录内")
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ValueError(f"不支持的文件类型: {path.suffix}")

        source = path.relative_to(self.root).as_posix()
        text = extract_text(path)
        parts = chunk_text(text, self.chunk_size, self.overlap)
        embeddings = self._embed_texts(parts)
        stat = path.stat()
        new_chunks = [
            StoredChunk(
                id=self._chunk_id(source, part),
                source=source,
                text=part,
                embedding=vector,
                mtime=stat.st_mtime,
                size=stat.st_size,
            )
            for part, vector in zip(parts, embeddings)
        ]

        with self._lock:
            self._chunks = [chunk for chunk in self._chunks if chunk.source != source]
            self._chunks.extend(new_chunks)
            self._save()

        return {
            "source": source,
            "chunks": len(new_chunks),
            "chars": len(text),
            "indexed": True,
        }

    def ingest_all(self, force: bool = False) -> dict[str, Any]:
        results = []
        for doc in self.list_documents():
            path = self.root / doc["name"]
            if not force and doc["indexed"]:
                # Re-index if file changed.
                existing = next((c for c in self._chunks if c.source == doc["name"]), None)
                if existing and existing.mtime == path.stat().st_mtime and existing.size == path.stat().st_size:
                    continue
            results.append(self.ingest_file(path))
        return {"ingested": results, "total_chunks": len(self._chunks)}

    def delete_document(self, name: str) -> dict[str, Any]:
        path = (self.root / name).resolve()
        if self.root not in path.parents and path != self.root:
            raise ValueError("非法路径")
        removed_file = False
        if path.is_file():
            path.unlink()
            removed_file = True
        with self._lock:
            before = len(self._chunks)
            self._chunks = [chunk for chunk in self._chunks if chunk.source != name]
            self._save()
        return {
            "source": name,
            "removed_file": removed_file,
            "removed_chunks": before - len(self._chunks),
        }

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        if not query.strip():
            return {"query": query, "results": []}
        if not self._chunks:
            return {"query": query, "results": [], "message": "知识库为空或尚未建立 embedding 索引"}

        query_vec = self._embed_texts([query])[0]
        ranked = [
            (self._cosine(query_vec, chunk.embedding), chunk)
            for chunk in self._chunks
        ]
        ranked.sort(key=lambda item: item[0], reverse=True)
        top = ranked[: max(1, min(limit, 10))]
        return {
            "query": query,
            "results": [
                {
                    "source": chunk.source,
                    "score": round(score, 4),
                    "text": chunk.text,
                }
                for score, chunk in top
                if score > 0
            ],
        }

    def answer_context(self, query: str, limit: int = 5) -> str:
        result = self.search(query, limit)
        if not result["results"]:
            return "未检索到相关资料。"
        lines = []
        for i, item in enumerate(result["results"], start=1):
            lines.append(f"[{i}] 来源: {item['source']} (相似度 {item['score']})\n{item['text']}")
        return "\n\n".join(lines)
