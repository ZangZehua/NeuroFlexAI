import json
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import wowo_agent.server as server_module
from wowo_agent.agent import Agent
from wowo_agent.cad import (
    CADArtifactStore,
    CADPlan,
    CircleHole,
    RectCutout,
    render_dxf,
    render_svg,
)
from wowo_agent.config import Settings
from wowo_agent.documents import chunk_text
from wowo_agent.embeddings import EmbeddingStore
from wowo_agent.knowledge_bases import KnowledgeBaseManager
from wowo_agent.rag import LocalKnowledgeBase
from wowo_agent.skills import SkillManager
from wowo_agent.tools import Permission, Tool, ToolRegistry


def test_local_rag_returns_source(tmp_path: Path):
    (tmp_path / "guide.md").write_text("部署建议使用 Linux 和 PostgreSQL。", encoding="utf-8")
    result = LocalKnowledgeBase(tmp_path).search("Linux PostgreSQL")
    assert result["results"][0]["source"] == "guide.md"


def test_denied_tool_is_not_executed():
    registry = ToolRegistry()
    registry.register(Tool("danger", "", {"type": "object"}, lambda: "bad", Permission.DENY))
    assert "工具被禁止" in registry.execute("danger", {})


def test_chunk_text_respects_size():
    text = "abcdefghij" * 50
    chunks = chunk_text(text, chunk_size=100, overlap=20)
    assert chunks
    assert all(len(c) <= 100 for c in chunks)


def test_embedding_store_search_uses_vectors(tmp_path: Path):
    doc = tmp_path / "note.txt"
    doc.write_text("向量检索用于 RAG。", encoding="utf-8")

    client = MagicMock()

    def fake_embed(model, input):
        texts = input if isinstance(input, list) else [input]
        data = []
        for i, text in enumerate(texts):
            # Simple bag-of-chars style fake embedding for ranking.
            vec = [0.0, 0.0, 0.0]
            if "向量" in text or "RAG" in text or "检索" in text:
                vec = [1.0, 0.0, 0.0]
            if "天气" in text:
                vec = [0.0, 1.0, 0.0]
            item = MagicMock()
            item.index = i
            item.embedding = vec
            data.append(item)
        resp = MagicMock()
        resp.data = data
        return resp

    client.embeddings.create.side_effect = fake_embed
    store = EmbeddingStore(tmp_path, client=client, model="fake-embed")
    store.ingest_file(doc)
    result = store.search("如何做 RAG 检索", limit=3)
    assert result["results"]
    assert result["results"][0]["source"] == "note.txt"


def test_agent_exposes_latest_tool_output():
    registry = ToolRegistry()
    registry.register(
        Tool(
            "retrieve_documents",
            "",
            {"type": "object"},
            lambda query, limit: {"results": [{"source": "note.txt", "text": query}]},
        )
    )

    tool_call = MagicMock()
    tool_call.id = "call-1"
    tool_call.function.name = "retrieve_documents"
    tool_call.function.arguments = '{"query":"RAG","limit":1}'

    first_message = MagicMock(content=None, tool_calls=[tool_call])
    second_message = MagicMock(content="回答", tool_calls=[])
    first = MagicMock(choices=[MagicMock(message=first_message)])
    second = MagicMock(choices=[MagicMock(message=second_message)])
    client = MagicMock()
    client.chat.completions.create.side_effect = [first, second]

    agent = Agent(client, "test-model", registry)
    assert agent.run("问题") == "回答"
    assert agent.last_tool_outputs["retrieve_documents"]["results"][0]["source"] == "note.txt"


def test_knowledge_base_manager_isolates_and_persists_profiles(tmp_path: Path):
    manager = KnowledgeBaseManager(tmp_path)
    created = manager.create("论文库")
    custom_path = manager.current()["path"]
    (custom_path / "paper.md").write_text("独立资料", encoding="utf-8")

    manager.rename(created["id"], "论文方案")
    manager.select("default")
    (tmp_path / "default.md").write_text("默认资料", encoding="utf-8")

    default_docs = LocalKnowledgeBase(tmp_path).list_documents()
    assert [doc["name"] for doc in default_docs] == ["default.md"]

    reloaded = KnowledgeBaseManager(tmp_path)
    assert reloaded.list()["current"] == "default"
    assert any(item["name"] == "论文方案" for item in reloaded.list()["knowledge_bases"])

    reloaded.delete(created["id"])
    assert not custom_path.exists()


def test_skill_manager_initializes_default_and_persists_changes(tmp_path: Path):
    manager = SkillManager(tmp_path)
    assert manager.current()["content"] == "输出你好，这是默认skill"

    created = manager.create("摘要 Skill", "只输出三条摘要")
    manager.update(created["id"], "精简摘要", "只输出一条摘要")
    assert SkillManager(tmp_path).current()["content"] == "只输出一条摘要"

    manager.delete(created["id"])
    assert manager.current()["id"] == "default"


def _sample_cad_plan() -> CADPlan:
    return CADPlan(
        title="安装板",
        summary="用于设备固定的铝合金安装板。",
        material="6061 铝合金",
        width=200,
        height=120,
        thickness=3,
        quantity=2,
        holes=[CircleHole(x=12, y=12, diameter=6)],
        cutouts=[RectCutout(x=80, y=50, width=40, height=20)],
        manufacturing_steps=["下料", "钻孔和铣槽", "去毛刺并检验"],
        notes=["未注公差由工程师确认"],
    )


def test_cad_renderers_create_outline_features_and_dimensions():
    plan = _sample_cad_plan()
    plan.validate_geometry()
    dxf = render_dxf(plan)
    svg = render_svg(plan)

    assert "LWPOLYLINE" in dxf
    assert "CIRCLE" in dxf
    assert "$INSUNITS" in dxf
    assert "<circle" in svg
    assert "200 mm" in svg


def test_cad_geometry_rejects_out_of_bounds_feature():
    plan = _sample_cad_plan()
    plan.holes = [CircleHole(x=1, y=1, diameter=6)]

    try:
        plan.validate_geometry()
    except ValueError as exc:
        assert "超出板件" in str(exc)
    else:
        raise AssertionError("越界圆孔应被拒绝")


def test_cad_artifact_store_writes_and_safely_resolves_files(tmp_path: Path):
    artifact = CADArtifactStore(tmp_path).create(_sample_cad_plan())
    job_id = artifact["id"]

    assert CADArtifactStore(tmp_path).resolve(job_id, "drawing.dxf").is_file()
    assert CADArtifactStore(tmp_path).resolve(job_id, "drawing.dwg").is_file()
    assert CADArtifactStore(tmp_path).resolve(job_id, "preview.svg").is_file()
    try:
        CADArtifactStore(tmp_path).resolve("../bad", "drawing.dxf")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("非法 CAD 文件路径应被拒绝")


def test_cad_artifact_store_writes_binary_dwg(tmp_path: Path):
    artifact = CADArtifactStore(tmp_path).create(_sample_cad_plan())
    dwg_path = CADArtifactStore(tmp_path).resolve(artifact["id"], "drawing.dwg")
    data = dwg_path.read_bytes()
    assert data[:6] == b"AC1015"
    assert b"AC1015" in data
    # Should be a binary file, not a text DXF.
    assert b"%PDF" not in data
    # A real binary DWG can be read back by ezdwg.
    from ezdwg.document import read

    doc = read(str(dwg_path))
    assert doc.version == "AC1015"
    entities = list(doc.modelspace().iter_entities())
    assert entities, "DWG 应包含可读取的几何实体"


def test_cad_api_generates_preview_and_downloadable_dxf(tmp_path: Path, monkeypatch):
    plan = _sample_cad_plan().model_dump()
    plan["manufacturing_steps"] = json.dumps(plan["manufacturing_steps"], ensure_ascii=False)
    tool_call = MagicMock()
    tool_call.function.name = "submit_cad_plan"
    tool_call.function.arguments = json.dumps(plan, ensure_ascii=False)
    response_message = MagicMock(content=None, tool_calls=[tool_call])
    client = MagicMock()
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=response_message)]
    )
    monkeypatch.setattr(server_module, "create_chat_client", lambda settings: client)
    app = server_module.create_app(
        Settings(
            api_key="test-key",
            knowledge_dir=tmp_path / "knowledge",
            skill_dir=tmp_path / "skills",
        )
    )

    web = TestClient(app)
    generated = web.post(
        "/api/cad/generate",
        json={"description": "制作一块 200×120×3 mm 的 6061 铝板并按给定位置开孔。"},
    )
    assert generated.status_code == 200
    payload = generated.json()
    assert payload["plan"]["title"] == "安装板"
    assert web.get(payload["artifact"]["svg_url"]).status_code == 200
    dxf = web.get(payload["artifact"]["dxf_url"])
    assert dxf.status_code == 200
    assert "CIRCLE" in dxf.text
    # DWG artifact is generated and served with the CAD API too.
    dwg = web.get(payload["artifact"]["dwg_url"])
    assert dwg.status_code == 200
    assert dwg.content[:6] == b"AC1015"


def _tool_response(arguments: str):
    tool_call = MagicMock()
    tool_call.function.name = "submit"
    tool_call.function.arguments = arguments
    return MagicMock(content=None, tool_calls=[tool_call])


def test_solution_planner_generates_distinct_options_with_pros_cons():
    from wowo_agent.planner import SolutionPlanner

    arguments = json.dumps(
        {
            "options": [
                {
                    "title": "方案甲",
                    "approach": "采用材料 A 的整体式结构设计",
                    "advantages": ["结构简单", "成本低"],
                    "disadvantages": ["可维护性差"],
                    "applicable_scenarios": "批量生产",
                },
                {
                    "title": "方案乙",
                    "approach": "采用模块化分体式结构，便于拆装",
                    "advantages": ["易维护", "可扩展"],
                    "disadvantages": ["成本较高"],
                    "applicable_scenarios": "科研试验",
                },
            ],
            "recommendation": "推荐方案甲",
        },
        ensure_ascii=False,
    )
    client = MagicMock()
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=_tool_response(arguments))]
    )
    bundle = SolutionPlanner(client, "test-model", num_options=2).plan("设计一个测试装置", [])
    assert len(bundle.options) == 2
    assert bundle.options[0].advantages and bundle.options[0].disadvantages
    assert bundle.recommendation == "推荐方案甲"


def test_solution_planner_rejects_same_strategy_options():
    from wowo_agent.planner import SolutionPlanner

    same = "统一采用激光切割成型工艺"
    arguments = json.dumps(
        {
            "options": [
                {
                    "title": "方案甲",
                    "approach": same,
                    "advantages": ["低"],
                    "disadvantages": ["高"],
                },
                {
                    "title": "方案乙",
                    "approach": same,
                    "advantages": ["低"],
                    "disadvantages": ["高"],
                },
            ],
            "recommendation": "方案甲",
        },
        ensure_ascii=False,
    )
    client = MagicMock()
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=_tool_response(arguments))]
    )
    planner = SolutionPlanner(client, "test-model", num_options=2)
    try:
        planner.plan("设计一个测试装置", [])
    except ValueError as exc:
        assert "未真正区分" in str(exc)
    else:
        raise AssertionError("仅参数不同/思路相同的方案应被拒绝")


def test_reflector_estimates_uncertainty_and_revises_answer():
    from wowo_agent.planner import Reflector

    low = _tool_response(
        json.dumps(
            {
                "confidence": 0.3,
                "grounded": False,
                "gaps": ["缺少材料规格依据"],
                "self_critique": "结论缺乏资料支撑",
                "revised_answer": "资料不足，无法给出确定结论",
            },
            ensure_ascii=False,
        )
    )
    high = _tool_response(
        json.dumps(
            {
                "confidence": 0.9,
                "grounded": True,
                "gaps": [],
                "self_critique": "已核对资料",
                "revised_answer": "基于资料的确定回答",
            },
            ensure_ascii=False,
        )
    )
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        MagicMock(choices=[MagicMock(message=low)]),
        MagicMock(choices=[MagicMock(message=high)]),
    ]
    reflection = Reflector(client, "test-model", max_iterations=2).reflect_answer(
        "问题", "草稿", [{"source": "a.md", "text": "资料"}]
    )
    assert reflection.confidence == 0.9
    assert reflection.revised_answer == "基于资料的确定回答"
    assert reflection.iterations == 2
    assert reflection.grounded is True


def _routing_chat_client():
    """A client that routes each model call to the right subsystem based on the
    system prompt, so the enhanced /api/chat endpoint can be tested end-to-end."""
    agent_tool = MagicMock()
    agent_tool.id = "call-a"
    agent_tool.function.name = "retrieve_documents"
    agent_tool.function.arguments = '{"query":"测试","limit":5}'
    agent_tool_msg = MagicMock(content=None, tool_calls=[agent_tool])
    agent_final_msg = MagicMock(content="草稿回答", tool_calls=[])
    reflection_call = MagicMock()
    reflection_call.function.name = "submit"
    reflection_call.function.arguments = json.dumps(
        {
            "confidence": 0.9,
            "grounded": True,
            "gaps": [],
            "self_critique": "已核对",
            "revised_answer": "最终修正回答",
        },
        ensure_ascii=False,
    )
    reflection_msg = MagicMock(content=None, tool_calls=[reflection_call])
    plan_call = MagicMock()
    plan_call.function.name = "submit"
    plan_call.function.arguments = json.dumps(
        {
            "options": [
                {
                    "title": "路线甲",
                    "approach": "整体式设计",
                    "advantages": ["低"],
                    "disadvantages": ["高"],
                },
                {
                    "title": "路线乙",
                    "approach": "模块化设计",
                    "advantages": ["易维护"],
                    "disadvantages": ["贵"],
                },
            ],
            "recommendation": "推荐路线甲",
        },
        ensure_ascii=False,
    )
    plan_msg = MagicMock(content=None, tool_calls=[plan_call])

    responses = iter([agent_tool_msg, agent_final_msg, reflection_msg, plan_msg])

    def create(model, messages, tools=None, **kwargs):
        next_response = next(responses)
        return MagicMock(choices=[MagicMock(message=next_response)])

    client = MagicMock()
    client.chat.completions.create.side_effect = create
    return client


def test_chat_endpoint_returns_options_and_reflection(tmp_path: Path, monkeypatch):
    client = _routing_chat_client()
    monkeypatch.setattr(server_module, "create_chat_client", lambda settings: client)
    app = server_module.create_app(
        Settings(
            api_key="test-key",
            knowledge_dir=tmp_path / "knowledge",
            skill_dir=tmp_path / "skills",
        )
    )
    web = TestClient(app)
    resp = web.post(
        "/api/chat",
        json={"message": "请给出一个研究方案", "limit": 5},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["answer"] == "最终修正回答"
    assert len(payload["options"]) == 2
    assert payload["options"][0]["advantages"]
    assert payload["reflection"]["confidence"] == 0.9
    assert payload["reflection"]["grounded"] is True
