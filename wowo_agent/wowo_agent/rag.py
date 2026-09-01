from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .documents import SUPPORTED_SUFFIXES, chunk_text, extract_text
from .embeddings import EmbeddingStore

# Backward-compatible export used by tests and CLI.
__all__ = ["Chunk", "LocalKnowledgeBase", "EmbeddingStore", "SUPPORTED_SUFFIXES"]


@dataclass(frozen=True)
class Chunk:
    source: str
    text: str


class LocalKnowledgeBase:
    """Local RAG over knowledge files.

    If an OpenAI client is provided, retrieval uses embeddings.
    Otherwise falls back to a dependency-free token overlap scorer.
    """

    def __init__(
        self,
        root: Path,
        chunk_size: int = 800,
        overlap: int = 120,
        client: Any | None = None,
        embedding_model: str = "text-embedding-3-small",
        evolution: Any | None = None,
    ):
        self.root = root.resolve()
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.evolution = evolution
        self.store = EmbeddingStore(
            root=self.root,
            client=client,
            model=embedding_model,
            chunk_size=chunk_size,
            overlap=overlap,
        )

    def _boost(self, source: str) -> float:
        """Ranking multiplier from the evolution store (1.0 when disabled)."""
        if self.evolution is None:
            return 1.0
        return self.evolution.status_boost(source)

    # ------------------------------------------------------------- text cache

    @property
    def _cache_dir(self) -> Path:
        return self.root / ".text_cache"

    def _cache_index_path(self) -> Path:
        return self._cache_dir / "index.json"

    def _load_cache_index(self) -> dict[str, dict[str, Any]]:
        path = self._cache_index_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache_index(self, index: dict[str, dict[str, Any]]) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        temp = self._cache_index_path().with_suffix(".tmp")
        temp.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        temp.replace(self._cache_index_path())

    def _cached_text(self, path: Path, source: str, index: dict[str, dict[str, Any]]) -> str:
        """Return cached extracted text for a file, re-extracting only when the
        file's mtime/size changed. Greatly speeds up keyword search over many
        PDFs, which previously re-parsed every document on each query."""
        stat = path.stat()
        entry = index.get(source)
        if entry and entry.get("mtime") == stat.st_mtime and entry.get("size") == stat.st_size:
            cache_file = self._cache_dir / entry["file"]
            if cache_file.exists():
                return cache_file.read_text(encoding="utf-8", errors="ignore")
        try:
            text = extract_text(path)
        except Exception:
            return ""
        cache_file = self._cache_dir / (hashlib.sha1(source.encode("utf-8")).hexdigest()[:20] + ".txt")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(text, encoding="utf-8")
        index[source] = {"file": cache_file.name, "mtime": stat.st_mtime, "size": stat.st_size}
        return text

    def _chunks(self) -> list[Chunk]:
        if not self.root.exists():
            return []
        chunks: list[Chunk] = []
        index = self._load_cache_index()
        dirty = False
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(self.root)
            if any(part.startswith(".") for part in relative.parts):
                continue
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            source = relative.as_posix()
            text = self._cached_text(path, source, index)
            if not text:
                continue
            dirty = True
            for part in chunk_text(text, self.chunk_size, self.overlap):
                chunks.append(Chunk(source, part))
        if dirty:
            self._save_cache_index(index)
        return chunks

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return set(re.findall(r"[\w\u4e00-\u9fff]+", text.lower()))

    def search(self, query: str, limit: int = 5) -> dict:
        if self.store.client is not None:
            try:
                results = self.store.search(query, limit)
                return self._apply_boost_to_results(query, results)
            except Exception:
                # Fall back if embedding API is unavailable.
                pass

        terms = self._tokens(query)
        ranked = []
        for chunk in self._chunks():
            words = self._tokens(chunk.text)
            base = len(terms & words) / max(1, len(terms))
            if not base:
                continue
            score = base * self._boost(chunk.source)
            if score <= 0:
                continue
            ranked.append((score, chunk))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return {
            "query": query,
            "results": [
                {"source": chunk.source, "score": round(score, 3), "text": chunk.text}
                for score, chunk in ranked[: max(1, min(limit, 10))]
            ],
        }

    def _apply_boost_to_results(self, query: str, results: dict) -> dict:
        """Re-weight embedding results by lifecycle status and drop retired."""
        boosted = []
        for item in results.get("results", []):
            mult = self._boost(item["source"])
            if mult <= 0:
                continue
            item = dict(item)
            item["score"] = round(item["score"] * mult, 4)
            boosted.append(item)
        boosted.sort(key=lambda it: it["score"], reverse=True)
        results["results"] = boosted
        return results

    def list_documents(self) -> list[dict]:
        documents = self.store.list_documents()
        if self.store.client is not None:
            return documents
        for document in documents:
            path = self.root / document["name"]
            try:
                document["chunks"] = len(
                    chunk_text(extract_text(path), self.chunk_size, self.overlap)
                )
                document["indexed"] = True
                document["index_mode"] = "keyword"
            except Exception:
                document["indexed"] = False
        return documents

    def ingest_file(self, path: Path) -> dict:
        if self.store.client is None:
            path = path.resolve()
            if not path.is_file() or self.root not in path.parents:
                raise ValueError("文件必须位于知识库目录内")
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                raise ValueError(f"不支持的文件类型: {path.suffix}")
            text = extract_text(path)
            parts = chunk_text(text, self.chunk_size, self.overlap)
            return {
                "source": path.relative_to(self.root).as_posix(),
                "chunks": len(parts),
                "chars": len(text),
                "indexed": True,
                "index_mode": "keyword",
            }
        return self.store.ingest_file(path)

    def ingest_all(self, force: bool = False) -> dict:
        if self.store.client is None:
            results = [self.ingest_file(self.root / item["name"]) for item in self.list_documents()]
            return {"ingested": results, "total_chunks": sum(item["chunks"] for item in results)}
        return self.store.ingest_all(force=force)

    def delete_document(self, name: str) -> dict:
        return self.store.delete_document(name)
