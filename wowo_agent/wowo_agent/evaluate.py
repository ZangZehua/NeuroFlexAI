"""High-level knowledge/capability evaluation facade for the self-evolving loop.

Wraps the persistent ``EvolutionStore`` (feedback.py) with the rule-engine
driven consolidation/retirement logic, exposing a small API used by the
web server and tests.
"""

from __future__ import annotations

from typing import Any

from .feedback import EvolutionStore, FeedbackKind, LifecycleStatus


class Evaluator:
    """Evaluates feedback, updates effectiveness, and drives lifecycle."""

    def __init__(self, store: EvolutionStore):
        self.store = store

    def record(
        self,
        rating: str,
        answer_id: str | None = None,
        correction: str | None = None,
        sources: list[str] | None = None,
        kind: FeedbackKind = FeedbackKind.HUMAN,
    ) -> dict[str, Any]:
        """Record feedback and apply it to the referenced knowledge sources."""
        if rating not in {"good", "bad"}:
            raise ValueError("rating 必须为 good 或 bad")
        feedback = self.store.record_feedback(
            rating=rating,
            answer_id=answer_id,
            correction=correction,
            sources=sources,
            kind=kind,
        )
        changes = self.store.apply_feedback_to_sources(feedback)
        return {
            "feedback": feedback,
            "source_status_changes": changes,
        }

    def record_capability(self, cap_id: str, rating: str) -> dict[str, Any]:
        if rating not in {"good", "bad"}:
            raise ValueError("rating 必须为 good 或 bad")
        return self.store.apply_capability_feedback(cap_id, rating)

    def report(self) -> dict[str, Any]:
        return {
            "knowledge": self.store.eval_table(),
            "capabilities": self.store.capability_table(),
            "feedback_count": len(self.store.list_feedback()),
        }
