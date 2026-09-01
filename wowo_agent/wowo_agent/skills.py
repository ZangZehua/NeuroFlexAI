from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any


class SkillManager:
    """Persist named prompt skills and the active selection."""

    DEFAULT_ID = "default"
    DEFAULT_CONTENT = "输出你好，这是默认skill"

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.root / "skills.json"
        self._lock = threading.RLock()
        self._data = self._load()
        if not self.registry_path.exists():
            self._save()

    def _default_data(self) -> dict[str, Any]:
        return {
            "current": self.DEFAULT_ID,
            "skills": [
                {
                    "id": self.DEFAULT_ID,
                    "name": "默认 Skill",
                    "content": self.DEFAULT_CONTENT,
                }
            ],
        }

    def _load(self) -> dict[str, Any]:
        default = self._default_data()
        if not self.registry_path.exists():
            return default
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            skills = data.get("skills", [])
            ids = {item.get("id") for item in skills}
            if self.DEFAULT_ID not in ids:
                skills.insert(0, default["skills"][0])
            current = data.get("current", self.DEFAULT_ID)
            if current not in {item.get("id") for item in skills}:
                current = self.DEFAULT_ID
            return {"current": current, "skills": skills}
        except (OSError, json.JSONDecodeError, TypeError):
            return default

    def _save(self) -> None:
        payload = json.dumps(self._data, ensure_ascii=False, indent=2)
        temp = self.registry_path.with_suffix(".tmp")
        temp.write_text(payload, encoding="utf-8")
        temp.replace(self.registry_path)

    @staticmethod
    def _clean(name: str, content: str) -> tuple[str, str]:
        clean_name = " ".join(name.split()).strip()
        clean_content = content.strip()
        if not clean_name:
            raise ValueError("Skill 名称不能为空")
        if len(clean_name) > 80:
            raise ValueError("Skill 名称不能超过 80 个字符")
        if not clean_content:
            raise ValueError("Skill 内容不能为空")
        if len(clean_content) > 20000:
            raise ValueError("Skill 内容不能超过 20000 个字符")
        return clean_name, clean_content

    def _find(self, skill_id: str) -> dict[str, str]:
        item = next((item for item in self._data["skills"] if item["id"] == skill_id), None)
        if item is None:
            raise KeyError("Skill 不存在")
        return item

    def list(self) -> dict[str, Any]:
        with self._lock:
            return {
                "current": self._data["current"],
                "skills": [
                    {
                        **item,
                        "is_default": item["id"] == self.DEFAULT_ID,
                        "suspended": bool(item.get("suspended")),
                    }
                    for item in self._data["skills"]
                ],
            }

    def current(self, active_only: bool = True) -> dict[str, Any]:
        with self._lock:
            if active_only:
                active = [
                    item
                    for item in self._data["skills"]
                    if not item.get("suspended") and item["id"] != self.DEFAULT_ID
                ]
                if active:
                    item = active[0]
                    self._data["current"] = item["id"]
                    return {**item, "is_default": False}
            item = self._find(self._data["current"])
            return {**item, "is_default": item["id"] == self.DEFAULT_ID}

    def evolve(self, capability_table: list[dict[str, Any]]) -> dict[str, Any]:
        """Auto-suspend capabilities that the evolution store retired.

        Manual selection stays authoritative: only non-default skills whose
        capability entry reached ``retired`` status are suspended, and the
        current selection is preserved unless it becomes suspended.
        """
        retired = {
            entry["id"]
            for entry in capability_table
            if entry.get("status") == "retired"
        }
        changes: dict[str, str] = {}
        with self._lock:
            for item in self._data["skills"]:
                if item["id"] == self.DEFAULT_ID:
                    continue
                suspended = bool(item.get("suspended"))
                should_suspend = item["id"] in retired
                if should_suspend and not suspended:
                    item["suspended"] = True
                    changes[item["id"]] = "active->suspended"
                elif suspended and not should_suspend:
                    item["suspended"] = False
                    changes[item["id"]] = "suspended->active"
            if changes and self._data["current"] in retired:
                self._data["current"] = self.DEFAULT_ID
            self._save()
            return {"changes": changes, "current": self._data["current"]}

    def create(self, name: str, content: str) -> dict[str, Any]:
        with self._lock:
            clean_name, clean_content = self._clean(name, content)
            if any(item["name"].casefold() == clean_name.casefold() for item in self._data["skills"]):
                raise ValueError("Skill 名称已存在")
            item = {
                "id": uuid.uuid4().hex[:12],
                "name": clean_name,
                "content": clean_content,
            }
            self._data["skills"].append(item)
            self._data["current"] = item["id"]
            self._save()
            return {**item, "is_default": False}

    def select(self, skill_id: str) -> dict[str, Any]:
        with self._lock:
            item = self._find(skill_id)
            self._data["current"] = skill_id
            self._save()
            return {**item, "is_default": skill_id == self.DEFAULT_ID}

    def update(self, skill_id: str, name: str, content: str) -> dict[str, Any]:
        with self._lock:
            clean_name, clean_content = self._clean(name, content)
            if any(
                item["id"] != skill_id and item["name"].casefold() == clean_name.casefold()
                for item in self._data["skills"]
            ):
                raise ValueError("Skill 名称已存在")
            item = self._find(skill_id)
            item.update(name=clean_name, content=clean_content)
            self._save()
            return {**item, "is_default": skill_id == self.DEFAULT_ID}

    def delete(self, skill_id: str) -> dict[str, Any]:
        with self._lock:
            if skill_id == self.DEFAULT_ID:
                raise ValueError("默认 Skill 不能删除")
            item = self._find(skill_id)
            self._data["skills"] = [
                candidate for candidate in self._data["skills"] if candidate["id"] != skill_id
            ]
            if self._data["current"] == skill_id:
                self._data["current"] = self.DEFAULT_ID
            self._save()
            return {"deleted": item, "current": self._data["current"]}
