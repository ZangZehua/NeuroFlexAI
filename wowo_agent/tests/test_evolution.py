import json
from pathlib import Path

from fastapi.testclient import TestClient

import wowo_agent.server as server_module
from wowo_agent.evaluate import Evaluator
from wowo_agent.feedback import EvolutionConfig, EvolutionStore, LifecycleStatus
from wowo_agent.rag import LocalKnowledgeBase
from wowo_agent.skills import SkillManager


def _store(tmp_path: Path) -> EvolutionStore:
    return EvolutionStore(tmp_path / ".evolution")


def test_record_feedback_is_persisted(tmp_path: Path):
    store = _store(tmp_path)
    feedback = store.record_feedback(
        rating="bad", answer_id="a1", correction="应该用硅胶而非 PDMS", sources=["p1.md"]
    )
    assert feedback["rating"] == "bad"
    stored = store.list_feedback()
    assert len(stored) == 1
    assert stored[0]["answer_id"] == "a1"
    assert stored[0]["sources"] == ["p1.md"]


def test_repeated_good_feedback_consolidates_source(tmp_path: Path):
    store = _store(tmp_path)
    cfg = EvolutionConfig(consolidate_min_hits=3, consolidate_score=0.6)
    store.config = cfg
    ev = Evaluator(store)
    for _ in range(3):
        ev.record(rating="good", sources=["good.md"])
    entry = store.get_eval("good.md")
    assert entry["status"] == LifecycleStatus.CONSOLIDATED.value
    assert entry["hits"] == 3
    assert store.status_boost("good.md") > 1.0


def test_repeated_bad_feedback_retires_source(tmp_path: Path):
    store = _store(tmp_path)
    ev = Evaluator(store)
    for _ in range(3):
        ev.record(rating="bad", correction="错误", sources=["bad.md"])
    entry = store.get_eval("bad.md")
    assert entry["status"] == LifecycleStatus.RETIRED.value
    assert store.status_boost("bad.md") == 0.0


def test_retired_source_excluded_from_keyword_search(tmp_path: Path):
    (tmp_path / "good.md").write_text("Use liquid metal and silicone for stretchable electrodes.", encoding="utf-8")
    (tmp_path / "bad.md").write_text("Use liquid metal and silicone for stretchable electrodes.", encoding="utf-8")
    store = _store(tmp_path)
    kb = LocalKnowledgeBase(tmp_path, evolution=store)
    for _ in range(3):
        store.record_feedback(rating="bad", sources=["bad.md"])
        store.apply_feedback_to_sources(store.list_feedback()[-1])

    results = kb.search("liquid metal stretchable electrodes", limit=10)["results"]
    sources = [r["source"] for r in results]
    assert "bad.md" not in sources
    assert "good.md" in sources


def test_consolidated_source_boosted_in_keyword_search(tmp_path: Path):
    (tmp_path / "a.md").write_text("Liquid metal for stretchable electrodes.", encoding="utf-8")
    (tmp_path / "b.md").write_text("Liquid metal for stretchable electrodes.", encoding="utf-8")
    store = _store(tmp_path)
    store.config = EvolutionConfig(consolidate_min_hits=3, consolidate_score=0.6)
    kb = LocalKnowledgeBase(tmp_path, evolution=store)
    for _ in range(3):
        store.record_feedback(rating="good", sources=["a.md"])
        store.apply_feedback_to_sources(store.list_feedback()[-1])
    results = kb.search("liquid metal stretchable electrodes", limit=10)["results"]
    assert results[0]["source"] == "a.md"


def test_skill_evolve_suspends_retired_capability(tmp_path: Path):
    store = _store(tmp_path)
    sm = SkillManager(tmp_path / "skills")
    created = sm.create("装配 Skill", "按规范装配")
    ev = Evaluator(store)
    for _ in range(3):
        ev.record_capability(created["id"], "bad")
    changes = sm.evolve(store.capability_table())
    assert created["id"] in changes["changes"]
    assert changes["changes"][created["id"]] == "active->suspended"
    assert sm.current()["id"] == SkillManager.DEFAULT_ID


def test_feedback_api_evolves_knowledge_and_skills(tmp_path: Path, monkeypatch):
    from wowo_agent.config import Settings

    monkeypatch.setattr(server_module, "create_chat_client", lambda s: object())
    app = server_module.create_app(
        Settings(
            api_key="test-key",
            knowledge_dir=tmp_path / "knowledge",
            skill_dir=tmp_path / "skills",
        )
    )
    web = TestClient(app)
    kb = server_module.KnowledgeBaseManager(tmp_path / "knowledge")
    base_path = kb.current()["path"]
    (base_path / "note.md").write_text("液态金属电极。", encoding="utf-8")

    for _ in range(3):
        resp = web.post(
            "/api/feedback",
            json={
                "rating": "bad",
                "correction": "应为硅胶",
                "sources": [{"source": "note.md"}],
            },
        )
        assert resp.status_code == 200
    report = web.get("/api/evolution").json()
    sources = {s["source"]: s for s in report["knowledge"]["sources"]}
    assert sources["note.md"]["status"] == LifecycleStatus.RETIRED.value
