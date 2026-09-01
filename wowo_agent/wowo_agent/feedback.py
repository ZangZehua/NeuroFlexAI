"""Feedback persistence and evaluation state for the self-evolving loop.

This module owns the on-disk state that drives the knowledge/capability
lifecycle:

* ``feedback.jsonl``  -- append-only log of human (or experiment) feedback.
* ``knowledge_eval.json`` -- per-source effectiveness/status table used to
  consolidate (boost) or retire (demote) knowledge snippets.
* ``capabilities.json`` -- per-skill effectiveness/status table used to
  suspend or promote capability carriers (Skills).

Lifecycle status transitions:

    pending -> validated -> consolidated
                         -> retired

* ``consolidated``: knowledge/skill is repeatedly useful; boosted in ranking.
* ``retired``: repeatedly corrected / low effectiveness; demoted or excluded.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from enum import StrEnum
from pathlib import Path
from typing import Any


class FeedbackKind(StrEnum):
    HUMAN = "human"
    EXPERIMENT = "experiment"


class LifecycleStatus(StrEnum):
    PENDING = "pending"
    VALIDATED = "validated"
    CONSOLIDATED = "consolidated"
    RETIRED = "retired"


class EvolutionConfig:
    """Thresholds that drive the consolidation/retirement rule engine."""

    def __init__(
        self,
        consolidate_score: float = 0.7,
        consolidate_min_hits: int = 3,
        retire_score: float = 0.35,
        retire_min_corrections: int = 2,
    ):
        self.consolidate_score = consolidate_score
        self.consolidate_min_hits = consolidate_min_hits
        self.retire_score = retire_score
        self.retire_min_corrections = retire_min_corrections


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class EvolutionStore:
    """Persist feedback records and per-source knowledge evaluation state."""

    EVAL_FILENAME = "knowledge_eval.json"
    CAP_FILENAME = "capabilities.json"
    FEEDBACK_FILENAME = "feedback.jsonl"

    def __init__(self, root: Path, config: EvolutionConfig | None = None):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.config = config or EvolutionConfig()
        self._lock = threading.RLock()
        self.eval_path = self.root / self.EVAL_FILENAME
        self.cap_path = self.root / self.CAP_FILENAME
        self.feedback_path = self.root / self.FEEDBACK_FILENAME
        self._eval: dict[str, dict[str, Any]] = self._load_json(self.eval_path)
        self._caps: dict[str, dict[str, Any]] = self._load_json(self.cap_path)

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_json(self, path: Path, data: dict[str, Any]) -> None:
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

    # ------------------------------------------------------------------ feedback

    def record_feedback(
        self,
        rating: str,
        answer_id: str | None = None,
        correction: str | None = None,
        sources: list[str] | None = None,
        kind: FeedbackKind = FeedbackKind.HUMAN,
    ) -> dict[str, Any]:
        """Append a feedback record and return it."""
        record = {
            "id": uuid.uuid4().hex[:12],
            "kind": kind.value,
            "rating": rating,
            "answer_id": answer_id,
            "correction": correction,
            "sources": sources or [],
            "timestamp": _now(),
        }
        with self._lock:
            with self.feedback_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def list_feedback(self) -> list[dict[str, Any]]:
        if not self.feedback_path.exists():
            return []
        records: list[dict[str, Any]] = []
        with self.feedback_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    # ------------------------------------------------------------- knowledge eval

    def get_eval(self, source: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._eval.get(source, {}))

    def apply_feedback_to_sources(self, feedback: dict[str, Any]) -> dict[str, Any]:
        """Update per-source effectiveness from a feedback record and run the
        lifecycle rule engine. Returns a summary of status changes."""
        rating = feedback.get("rating")
        correction = feedback.get("correction") or ""
        sources = feedback.get("sources") or []
        changes: dict[str, str] = {}
        with self._lock:
            for source in sources:
                entry = self._eval.setdefault(source, self._new_eval(source))
                if rating == "good":
                    entry["hits"] += 1
                    entry["effectiveness"] = min(1.0, entry["effectiveness"] + 0.25)
                elif rating == "bad":
                    entry["corrected"] += 1
                    entry["effectiveness"] = max(0.0, entry["effectiveness"] - 0.3)
                    if correction:
                        entry["last_correction"] = correction[:1000]
                entry["last_rating"] = rating
                entry["updated"] = _now()
                old_status = entry["status"]
                new_status = self._decide_status(entry)
                if new_status != old_status:
                    entry["status"] = new_status
                    entry["status_changed_at"] = _now()
                    changes[source] = f"{old_status}->{new_status}"
            self._save_json(self.eval_path, self._eval)
        return changes

    def _new_eval(self, source: str) -> dict[str, Any]:
        return {
            "source": source,
            "hits": 0,
            "corrected": 0,
            "effectiveness": 0.5,
            "last_rating": None,
            "status": LifecycleStatus.PENDING.value,
            "created": _now(),
            "updated": _now(),
        }

    def _decide_status(self, entry: dict[str, Any]) -> str:
        """Threshold rule engine for a single knowledge source."""
        effectiveness = entry.get("effectiveness", 0.5)
        hits = entry.get("hits", 0)
        corrected = entry.get("corrected", 0)
        if (
            effectiveness >= self.config.consolidate_score
            and hits >= self.config.consolidate_min_hits
        ):
            return LifecycleStatus.CONSOLIDATED.value
        # Retirement requires consistent correction (or an extremely low
        # effectiveness reached over repeated negative feedback), so a single
        # bad rating does not immediately purge useful knowledge.
        if corrected >= self.config.retire_min_corrections:
            return LifecycleStatus.RETIRED.value
        if (
            corrected >= 1
            and effectiveness <= self.config.retire_score * 0.5
        ):
            return LifecycleStatus.RETIRED.value
        if hits > 0 or corrected > 0:
            return LifecycleStatus.VALIDATED.value
        return LifecycleStatus.PENDING.value

    def eval_table(self) -> dict[str, Any]:
        with self._lock:
            return {
                "config": {
                    "consolidate_score": self.config.consolidate_score,
                    "consolidate_min_hits": self.config.consolidate_min_hits,
                    "retire_score": self.config.retire_score,
                    "retire_min_corrections": self.config.retire_min_corrections,
                },
                "sources": sorted(self._eval.values(), key=lambda e: e["source"]),
            }

    def status_boost(self, source: str) -> float:
        """Ranking multiplier: consolidated sources are boosted, retired are
        demoted/excluded. Applies to keyword search weighting."""
        with self._lock:
            entry = self._eval.get(source)
        if not entry:
            return 1.0
        status = entry.get("status", LifecycleStatus.PENDING.value)
        if status == LifecycleStatus.CONSOLIDATED:
            return 1.3
        if status == LifecycleStatus.RETIRED:
            return 0.0
        if status == LifecycleStatus.VALIDATED:
            return 1.15
        return 1.0

    # ------------------------------------------------------------- capabilities

    def capability(self, cap_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._caps.get(cap_id, {}))

    def apply_capability_feedback(self, cap_id: str, rating: str) -> dict[str, Any]:
        """Update a capability/skill score from feedback and run lifecycle."""
        with self._lock:
            entry = self._caps.setdefault(
                cap_id,
                {
                    "id": cap_id,
                    "score": 0.5,
                    "wins": 0,
                    "losses": 0,
                    "status": LifecycleStatus.PENDING.value,
                    "created": _now(),
                    "updated": _now(),
                },
            )
            if rating == "good":
                entry["wins"] += 1
                entry["score"] = min(1.0, entry["score"] + 0.2)
            else:
                entry["losses"] += 1
                entry["score"] = max(0.0, entry["score"] - 0.25)
            entry["updated"] = _now()
            old_status = entry["status"]
            entry["status"] = self._decide_capability_status(entry)
            changed = entry["status"] != old_status
            if changed:
                entry["status_changed_at"] = _now()
            self._save_json(self.cap_path, self._caps)
            return {"entry": dict(entry), "status_changed": changed}

    def _decide_capability_status(self, entry: dict[str, Any]) -> str:
        score = entry.get("score", 0.5)
        wins = entry.get("wins", 0)
        losses = entry.get("losses", 0)
        if score >= self.config.consolidate_score and wins >= self.config.consolidate_min_hits:
            return LifecycleStatus.CONSOLIDATED.value
        if losses >= self.config.retire_min_corrections:
            return LifecycleStatus.RETIRED.value
        if (
            losses >= 1
            and score <= self.config.retire_score * 0.5
        ):
            return LifecycleStatus.RETIRED.value
        if wins > 0 or losses > 0:
            return LifecycleStatus.VALIDATED.value
        return LifecycleStatus.PENDING.value

    def capability_table(self) -> dict[str, Any]:
        with self._lock:
            return sorted(self._caps.values(), key=lambda c: c.get("id", ""))
