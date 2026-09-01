from __future__ import annotations

import json
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any


class KnowledgeBaseManager:
    """Persist and isolate named local knowledge bases."""

    DEFAULT_ID = "default"

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.bases_root = self.root / ".bases"
        self.registry_path = self.root / ".knowledge_bases.json"
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        default = {
            "current": self.DEFAULT_ID,
            "bases": [{"id": self.DEFAULT_ID, "name": "默认知识库"}],
        }
        if not self.registry_path.exists():
            return default
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            bases = data.get("bases", [])
            ids = {item.get("id") for item in bases}
            if self.DEFAULT_ID not in ids:
                bases.insert(0, default["bases"][0])
            current = data.get("current", self.DEFAULT_ID)
            if current not in {item.get("id") for item in bases}:
                current = self.DEFAULT_ID
            return {"current": current, "bases": bases}
        except (OSError, json.JSONDecodeError, TypeError):
            return default

    def _save(self) -> None:
        payload = json.dumps(self._data, ensure_ascii=False, indent=2)
        temp = self.registry_path.with_suffix(".tmp")
        temp.write_text(payload, encoding="utf-8")
        temp.replace(self.registry_path)

    @staticmethod
    def _clean_name(name: str) -> str:
        cleaned = " ".join(name.split()).strip()
        if not cleaned:
            raise ValueError("知识库名称不能为空")
        if len(cleaned) > 80:
            raise ValueError("知识库名称不能超过 80 个字符")
        return cleaned

    def _find(self, base_id: str) -> dict[str, str]:
        item = next((item for item in self._data["bases"] if item["id"] == base_id), None)
        if item is None:
            raise KeyError("知识库不存在")
        return item

    def path_for(self, base_id: str) -> Path:
        self._find(base_id)
        if base_id == self.DEFAULT_ID:
            return self.root
        return self.bases_root / base_id

    def list(self) -> dict[str, Any]:
        with self._lock:
            return {
                "current": self._data["current"],
                "knowledge_bases": [
                    {
                        **item,
                        "is_default": item["id"] == self.DEFAULT_ID,
                    }
                    for item in self._data["bases"]
                ],
            }

    def current(self) -> dict[str, Any]:
        with self._lock:
            item = self._find(self._data["current"])
            return {**item, "path": self.path_for(item["id"])}

    def create(self, name: str) -> dict[str, Any]:
        with self._lock:
            cleaned = self._clean_name(name)
            if any(item["name"].casefold() == cleaned.casefold() for item in self._data["bases"]):
                raise ValueError("知识库名称已存在")
            base_id = uuid.uuid4().hex[:12]
            item = {"id": base_id, "name": cleaned}
            self._data["bases"].append(item)
            self._data["current"] = base_id
            self.path_for(base_id).mkdir(parents=True, exist_ok=True)
            self._save()
            return {**item, "is_default": False}

    def select(self, base_id: str) -> dict[str, Any]:
        with self._lock:
            item = self._find(base_id)
            self._data["current"] = base_id
            self.path_for(base_id).mkdir(parents=True, exist_ok=True)
            self._save()
            return {**item, "is_default": base_id == self.DEFAULT_ID}

    def rename(self, base_id: str, name: str) -> dict[str, Any]:
        with self._lock:
            cleaned = self._clean_name(name)
            if any(
                item["id"] != base_id and item["name"].casefold() == cleaned.casefold()
                for item in self._data["bases"]
            ):
                raise ValueError("知识库名称已存在")
            item = self._find(base_id)
            item["name"] = cleaned
            self._save()
            return {**item, "is_default": base_id == self.DEFAULT_ID}

    def delete(self, base_id: str) -> dict[str, Any]:
        with self._lock:
            if base_id == self.DEFAULT_ID:
                raise ValueError("默认知识库不能删除")
            item = self._find(base_id)
            shutil.rmtree(self.path_for(base_id), ignore_errors=True)
            self._data["bases"] = [
                candidate for candidate in self._data["bases"] if candidate["id"] != base_id
            ]
            if self._data["current"] == base_id:
                self._data["current"] = self.DEFAULT_ID
            self._save()
            return {"deleted": item, "current": self._data["current"]}
