# wowo_agent

使用 OpenAI 风格消息与工具调用的本地 RAG Agent，提供 CLI 与 Web 界面。支持导入 PDF、DOCX 等文件并做检索问答。

## 功能

- Web：拖拽/选择上传文件，自动解析并建立检索索引
- 多知识库方案：网页新建、选择、重命名保存和删除，索引相互隔离
- Skill 库：网页新建、选择、编辑和删除 Agent 指令
- 支持 `.pdf` / `.docx` / `.txt` / `.md` 等
- 默认使用本地持久化向量索引；对话接口不提供 embedding 时可切换本地关键词检索
- CLI 与 Web 均可基于检索结果回答并引用来源
- 方案生成输出多个在思路上真正不同的方案（仅参数不同不算多方案），每个方案给出优缺点与适用场景，并带有推荐意见
- 生成后自动自我校核（self-reflection）：评估置信度、标注不确定项、必要时缩小结论范围，规避“很自信地瞎说”
- 每个制作环节可分别选择对应的设备说明书（知识库）；某环节缺少说明书时可直接上传并自动建立新方案
- 制作流程各环节顺序可自由拖拽调整，无需固定先后
- 根据自然语言需求生成二维板件制作方案与参数化 CAD 图
- CAD 支持矩形外轮廓、圆孔、矩形开槽，提供 SVG 预览和 DWG/DXF/JSON 下载
- 出图前执行尺寸与几何边界校验，关键参数不足时要求补充而不猜测

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

## 配置

```bash
cp .env.example .env
# 编辑 .env，填入 OpenAI 兼容接口配置
export $(grep -v '^#' .env | xargs)   # 或按系统方式加载环境变量
```

关键变量：

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `OPENAI_API_KEY` | OpenAI 兼容接口密钥 | （必填） |
| `ZAI_API_KEY` | 智谱 API 密钥（可替代上一项） | （可选） |
| `OPENAI_BASE_URL` | OpenAI 兼容接口地址 | OpenAI 官方地址 |
| `OPENAI_MODEL` | 对话模型 | `gpt-5.4-mini` |
| `OPENAI_EMBEDDING_MODEL` | Embedding 模型 | `text-embedding-3-small` |
| `WOWO_EMBEDDINGS_ENABLED` | 是否调用 embedding API；关闭后使用本地关键词检索 | `1` |
| `OPENAI_TIMEOUT_SECONDS` | 单次 OpenAI 请求总超时 | `180` |
| `OPENAI_CONNECT_TIMEOUT_SECONDS` | OpenAI 连接超时 | `20` |
| `OPENAI_MAX_RETRIES` | OpenAI 请求重试次数 | `1` |
| `HTTPS_PROXY` / `HTTP_PROXY` | OpenAI 网络代理（按需配置） | （无） |
| `WOWO_KNOWLEDGE_DIR` | 知识库目录 | `knowledge` |
| `WOWO_SKILL_DIR` | Skill 持久化目录 | `skills` |
| `WOWO_HOST` / `WOWO_PORT` | Web 地址 | `127.0.0.1:8000` |

## 启动 Web 界面

```bash
python -m wowo_agent.server
# 或
wowo-web
```

浏览器打开 http://127.0.0.1:8000 ：

1. 上传 PDF / DOCX 等文件
2. 等待检索索引建立完成
3. 在右侧问答框提问

## CLI

```bash
python app.py "这篇论文的主要结论是什么？"
python app.py   # 交互模式
```

## API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET / POST | `/api/knowledge-bases` | 列出或新建知识库方案 |
| PUT | `/api/knowledge-bases/current` | 切换当前知识库 |
| PATCH / DELETE | `/api/knowledge-bases/{id}` | 重命名或删除知识库方案 |
| GET / POST | `/api/skills` | 列出或新建 Skill |
| PUT | `/api/skills/current` | 切换当前 Skill |
| PATCH / DELETE | `/api/skills/{id}` | 更新或删除 Skill |
| GET | `/api/documents` | 文档列表 |
| POST | `/api/upload` | 上传并建立检索索引 |
| POST | `/api/ingest` | 重建索引 |
| POST | `/api/search` | 仅检索 |
| POST | `/api/chat` | RAG 问答（含多方案生成、自我校核与置信度） |
| POST | `/api/cad/generate` | 生成制作方案、SVG 预览与 DWG/DXF CAD 图 |
| GET | `/api/cad/files/{id}/{filename}` | 下载 CAD 产物 |
| DELETE | `/api/documents` | 删除文档 |
| POST | `/api/feedback` | 记录人类/实验反馈，驱动知识巩固与淘汰（自进化闭环） |
| GET | `/api/evolution` | 查看知识/能力评估与生命周期状态报告 |

## 自进化闭环（反馈 → 巩固/淘汰）

Agent 会根据人类（或实验）反馈持续评估自己使用的知识与能力，自动完成巩固与淘汰：

1. `/api/chat` 每次回答都会返回 `answer_id` 与 `sources`。
2. 用户（或实验环节）通过 `POST /api/feedback` 提交评价：`{rating: good|bad, answer_id, correction?, sources?}`。
3. 系统按来源更新有效性分数：
   - `good`：`hits+1`、有效性 +0.25；
   - `bad`：`corrected+1`、有效性 -0.3（可附 `correction` 修正文本）。
4. **阈值规则引擎**（`feedback.py`）根据累计反馈决定生命周期状态：
   - `pending → validated → consolidated / retired`
   - **巩固 consolidated**：有效性≥0.7 且命中≥3 → 检索时加权（×1.3）。
   - **淘汰 retired**：被纠错≥2 次（或极低有效性）→ 检索时排除（×0）。
5. **能力载体（Skill）自动管理**：非默认 Skill 达到 `retired` 状态会自动停用（`suspended`），手动选择仍优先。
6. 持久化状态存于知识库根目录 `.evolution/`：`feedback.jsonl`、`knowledge_eval.json`、`capabilities.json`。

`POST /api/feedback` 返回示例：

```json
{
  "feedback": {"id": "...", "rating": "bad", "correction": "...", "sources": ["paper.pdf"], "kind": "human"},
  "source_status_changes": {"paper.pdf": "validated->retired"},
  "capability": {"entry": {"id": "...", "score": 0.1, "wins": 0, "losses": 3, "status": "retired"}},
  "skill_evolve": {"changes": {"<skill-id>": "active->suspended"}, "current": "default"}
}
```

## CAD 制图

在 Web 页面的“制作方案与 CAD 制图”区域输入板件需求。描述中应包含板件长、宽、厚度、材料，以及每个孔或开槽的位置和尺寸。例如：

```text
制作一块 200×120×3 mm 的 6061 铝板，数量 2。四角各开一个直径
6 mm 的圆孔，孔中心距相邻边均为 12 mm；中心开一个 40×20 mm 的矩形槽。
```

生成文件保存在当前知识库的隐藏 `.cad` 目录，不会被文档索引。同时输出 **DWG（二进制 R2000/AC1015，由 ezdwg 原生写入）**、DXF 与 SVG。DWG 与 DXF 均使用毫米单位，可由 AutoCAD、LibreCAD 或 FreeCAD 打开。当前版本为二维矩形板件制图，不包含三维实体或装配体建模。

## 多方案生成与自我校核

在“方案生成助手”中提问时，系统会：

1. **生成多种方案**：优先给出 2~3 个在技术思路上明显不同的方案（仅改变参数数值不算多个方案），每个方案列出优点、缺点与适用场景，并给出基于客观比较的推荐意见。
2. **自我校核（Self-reflection）**：对回答进行批判性复核，评估置信度（0~100%）、标注不确定项、必要时缩小结论范围并修正回答，从而规避“很自信地瞎说”的情况。

`/api/chat` 返回结构：

```json
{
  "answer": "修正后的最终回答",
  "sources": [...],
  "options": [
    {"title": "...", "approach": "...", "advantages": [...], "disadvantages": [...], "applicable_scenarios": "..."}
  ],
  "recommendation": "推荐意见",
  "reflection": {
    "confidence": 0.9,
    "grounded": true,
    "gaps": [],
    "self_critique": "...",
    "revised_answer": "...",
    "iterations": 2
  }
}
```

## 设备说明书与环节顺序

- 工作台顶部的流程条中，每个环节（资料准备 / 能力配置 / 方案生成 / CAD 出图）都可分别选择一个**设备说明书**（即知识库方案）。若某环节缺少说明书，选择“＋ 上传/新建说明书”即可上传文档并建立新方案。
- 各环节的**顺序可以自由拖拽调整**，不必固定先后，满足“各环节都涉及、但顺序不一定”的需求。
