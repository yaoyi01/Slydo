# Slydo 开发规范与开发计划

> 基于《开发设计说明书-v3.1.md》V3.1.1 版本整理
> 2026-05-06

---

> **上次更新：** 2026-05-10（C3 稳定化完成 / 推荐结果改为 20 条）
> **当前测试状态：** 82 单元测试 ✅ / 23 API 集成测试 ✅ / 0 失败
> **当前数据：** 33 文档 / 1265 slides / 1265 QS 已计算 / 0 页金牌标记
> **推荐配置：** TOP_N=20（默认返回 20 条推荐）

## 第一部分：开发规范

---

### 一、项目管理规范

#### 1.1 Git 工作流

| 分支 | 用途 | 来源 | 合并到 |
|:---|:---|:---|:---|
| `main` | 生产就绪代码 | — | — |
| `develop` | 日常开发集成分支 | `main` | `main` |
| `feature/*` | 单个功能开发 | `develop` | `develop` |
| `fix/*` | 缺陷修复 | `develop` | `develop` |
| `release/*` | 发布候选 | `develop` | `main` + `develop` |

**提交规范：** 使用约定式提交（Conventional Commits）：

```
feat: 新增 ETL 入库脚本 Phase 1 实现
fix: 修正 export_single_slide 缺少 import io 的问题
docs: 更新 API 接口文档
refactor: 重构 llm_rerank 去重逻辑
chore: 升级 pdf2image 依赖至 v3.0
```

**PR 规范：**

- 每个 PR 关联对应 Issue
- PR 描述包含：变更摘要、测试方法、影响范围
- 必须通过 CI 检查（lint + 类型检查 + 单元测试）
- 至少 1 人 Review 后方可合并

#### 1.2 Issue 管理

| 标签 | 含义 | 响应时间 |
|:---|:---|:---|
| `bug` | 系统缺陷 | 24h 内确认 |
| `enhancement` | 功能增强 | 下一迭代计划 |
| `question` | 技术疑问 | 48h 内回复 |
| `blocker` | 阻塞发布的问题 | 立即响应 |

---

### 二、代码规范

#### 2.1 Python 后端规范

**语言版本：** Python 3.11+

**编码风格：**

- 遵循 PEP 8 + Black 格式化（行宽 100）
- 类型注解必须完整（`mypy --strict` 通过）
- 使用 `async def` 和 `await` 范式（FastAPI 原生 asyncio）
- 所有外部 API 调用必须加 `@retry` 装饰器

**项目结构：**

```
slydo-backend/
├── app/
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 配置（环境变量读取）
│   ├── database.py             # PostgreSQL + Qdrant 连接
│   ├── models/
│   │   ├── deck.py             # decks 表 ORM
│   │   ├── slide.py            # slides 表 ORM
│   │   └── ...                 # tags, usage_log, deck_versions
│   ├── routers/
│   │   ├── ingest.py           # 入库 API
│   │   ├── recommend.py        # 推荐 API
│   │   ├── slides.py           # 单页导出 API
│   │   └── search.py           # 搜索 API
│   ├── services/
│   │   ├── etl/
│   │   │   ├── phase1_extract.py   # 文档解析 + 渲染
│   │   │   ├── phase2_vision.py    # 视觉模型含义提取
│   │   │   ├── phase3_store.py     # PG + Wiki 写入
│   │   │   ├── phase4_embed.py     # BGE-M3 嵌入 + Qdrant
│   │   │   └── phase5_quality.py   # 质量评分初始化
│   │   ├── recommend.py        # 推荐逻辑（多路召回 + llm_rerank）
│   │   ├── export.py           # 单页导出
│   │   └── watcher.py          # 目录监控守护进程
│   └── utils/
│       ├── llm.py              # DeepSeek API 封装
│       ├── vision.py           # Ollama 视觉模型封装
│       ├── retry.py            # 指数退避重试装饰器
│       ├── token_counter.py    # Token 成本估算
│       └── wiki_writer.py      # LLM Wiki 写入工具
├── etl_ingest.py               # 单文件入库入口
├── watcher.py                   # 目录监控入口
├── tests/
├── requirements.txt
└── pyproject.toml
```

**命名规范：**

| 单元 | 规范 | 示例 |
|:---|:---|:---|
| 函数/变量 | `snake_case` | `extract_slides()` |
| 类名 | `PascalCase` | `PptWatcher` |
| 常量 | `UPPER_SNAKE_CASE` | `OLLAMA_BASE` |
| 私有方法 | `_leading_underscore` | `_ingest()` |
| 数据库表 | `snake_case` 复数 | `deck_versions` |
| API 路由 | 小写 + 中横线 | `/api/slides/{id}/export` |

**错误处理规范：**

```python
class SlydoError(Exception):
    """基础异常类"""
    ...

class IngestError(SlydoError):
    """入库异常"""
    ...

def retry(max_retries=3, delay=2, backoff=2):
    """指数退避重试装饰器"""
    ...

async def safe_llm_call(prompt: str) -> str:
    """带熔断的 LLM 调用"""
    if circuit_breaker.is_open():
        raise ServiceUnavailable("LLM 服务熔断中")
    try:
        return await deepseek_chat(prompt)
    except RequestException as e:
        circuit_breaker.record_failure()
        raise
```

#### 2.2 数据库规范

**PostgreSQL：**

| 规则 | 说明 |
|:---|:---|
| 时间戳 | 所有表必须有 `created_at TIMESTAMPTZ DEFAULT NOW()` |
| 更新时间 | 变更型表添加 `updated_at` |
| 主键 | UUID 作为主键，SERIAL 仅用于字典表 |
| 外键 | 所有外键加 `ON DELETE CASCADE` |
| 索引命名 | `idx_<table>_<column>` |
| 迁移 | Schema 变更必须通过 Alembic 迁移脚本 |

**Qdrant：**

| 规则 | 说明 |
|:---|:---|
| Collection 名 | `snake_case`（如 `slides`） |
| Payload 字段 | `snake_case` |
| 向量维度 | 1024（BGE-M3） |
| 删除操作 | 必须用 `deck_id` 作为过滤条件 |

#### 2.3 VSTO 插件端规范

**语言版本：** C# 10.0+ / .NET 4.8+

**命名规范：**

| 单元 | 规范 | 示例 |
|:---|:---|:---|
| 类 | `PascalCase` | `SlydoRibbon`, `RecommendationPane` |
| 方法 | `PascalCase` | `ImportSlide`, `CallBackendAsync` |
| 变量 | `camelCase` | `localPath` |
| 私有字段 | `_camelCase` | `_apiClient` |

**异步调用：** 所有后端 API 调用必须使用 `async/await`。UI 线程调用建议使用 `async void` 事件处理器 + `ConfigureAwait(true)`。

#### 2.4 API 设计规范

**接口定义：**

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| `POST` | `/api/ingest` | 触发入库 |
| `GET` | `/api/slides/{id}` | 获取页面详情 |
| `GET` | `/api/slides/{id}/export` | 导出单页临时 PPT |
| `GET` | `/api/recommend` | 获取推荐结果 |
| `GET` | `/api/search` | 全文搜索 |
| `DELETE` | `/api/decks/{id}` | 删除文档（含级联清理） |
| `GET` | `/api/decks/by_path` | 按路径查询文档（watcher 用） |
| `POST` | `/api/decks/{id}/restore` | 从历史版本恢复 |
| `GET` | `/api/monitor/stats` | 入库监控统计数据 |
| `GET` | `/api/monitor/health` | 组件健康检测 |
| `GET` | `/dashboard` | 入库监控仪表盘 HTML |

**响应格式：**

```json
{
  "data": { ... },
  "meta": {
    "request_id": "xxx",
    "timestamp": "2026-05-06T10:00:00Z",
    "latency_ms": 123
  }
}
```

**错误格式：**

```json
{
  "error": {
    "code": "SLIDE_NOT_FOUND",
    "message": "页面不存在或已被删除",
    "detail": { "slide_id": "xxx" }
  }
}
```

---

### 三、测试规范

#### 3.1 测试金字塔

| 层级 | 覆盖目标 | 覆盖率目标 | 工具 |
|:---|:---|:---:|:---|
| 单元测试 | services/utils 各函数 | ≥ 80% | pytest |
| 集成测试 | API 路由 + 数据库交互 | ≥ 60% | pytest + httpx + 独立测试 DB |
| E2E 测试 | 完整入库→检索→导出流程 | 关键路径 | playwright + 测试 PPT 文件 |
| 视觉模型 E2E | 纯图片页含义提取、图表页布局识别、JSON 解析容错 | 关键路径 | Ollama 视觉模型 + 测试截图 |
| 性能测试 | 推荐响应时间 SLA | P95 < 5s | locust |

#### 3.2 测试用例编写规范

```python
# tests/test_etl_phase1.py

class TestExtractSlides:
    """Phase 1 文档解析测试"""

    def test_normal_pptx_extracts_all_slides(self):
        """正常 PPT 能正确提取所有页面"""
        result = extract_slides("fixtures/normal_10pages.pptx")
        assert len(result) == 10

    def test_image_only_slide_returns_empty_text(self):
        """纯图片页提取到空文本"""
        result = extract_slides("fixtures/image_only.pptx")[0]
        assert result["title"] == ""
        assert result["body"] == ""

    def test_corrupted_file_returns_empty_list(self):
        """损坏文件返回空列表而非抛异常"""
        result = extract_slides("fixtures/corrupted.pptx")
        assert result == []

    def test_notes_are_extracted_correctly(self):
        """备注页文本正确提取"""
        result = extract_slides("fixtures/with_notes.pptx")
        assert "备注内容" in result[0]["notes"]
```

#### 3.3 关键测试路径

| 模块 | 测试重点 |
|:---|:---|
| ETL 入库 | 正常解析、纯图片页、损坏文件、长文档(100页+)、去重逻辑 |
| 视觉模型 | API 超时重试、图片编码、JSON 解析容错 |
| 推荐引擎 | 双路去重、LLM 重排、空结果、边界 Top-K |
| 目录监控 | 新增/修改/删除事件、checksum 比对、并发写入 |
| 版本管理 | 版本递增、旧版数据回滚、超过2版本的清理 |
| 单页导出 | 文本页、图片页、表格页、大文件、并发请求 |
| Qdrant | 向量 upsert、按 deck_id 批量删除、搜索 |

---

### 四、环境与部署规范

#### 4.1 本地开发环境（WSL）

```bash
# 前置条件
python3.11 venv
PostgreSQL 16 + zhparser（复用现有实例，创建新 database slydo）
Qdrant 本地模式（复用 ~/.hybrid-kb/qdrant？否，Slydo 用独立 ~/.slydo/qdrant）
Ollama（bge-m3 + 视觉模型，复用宿主机 172.22.224.1:11434）
LibreOffice（headless mode，用于 PPT→PDF→PNG 渲染）

# 环境变量
DEEPSEEK_API_KEY=sk-xxx
OLLAMA_BASE_URL=http://172.22.224.1:11434
OLLAMA_VISION_MODEL=qwen3-vl:8b
DATABASE_URL=postgresql://slydo:***@localhost:5432/slydo
# ⚠️ 端口说明：当前 5432 由 hindsight 使用，如需独立实例用 5433
#   ❯ sudo -u postgres psql -c "CREATE DATABASE slydo;"
#   ❯ sudo -u postgres psql -c "CREATE USER slydo WITH PASSWORD '...';"
#   ❯ sudo -u postgres psql -d slydo -c "CREATE EXTENSION zhparser;"
QDRANT_PATH=~/.slydo/qdrant
SLYDO_WIKI_PATH=~/.slydo/wiki
```

> **环境复用清单：**
>
> | 组件 | 复用现有实例？ | 说明 |
> |:---|:---:|:---|
> | PostgreSQL | ✅ 复用（hindsight 实例） | 新建 database `slydo`，独立用户 |
> | Qdrant | ❌ 独立 | `~/.slydo/qdrant`，不与 hybrid-kb 共享 |
> | LLM Wiki | ❌ 独立 | `~/.slydo/wiki/`，不与 wiki-infosec/wiki-personal 共享 |
> | Ollama | ✅ 复用（Windows 宿主机） | bge-m3 + 视觉模型共用 |
> | DeepSeek API | ✅ 复用 | DEEPSEEK_API_KEY 共用 |
>
> > **与 hybrid-knowledge-base 的关系：** Slydo 使用与 hybrid-kb 相同的技术栈（Qdrant + LLM Wiki + PostgreSQL），
> > 但完全独立部署：独立的 Qdrant collection、独立的 Wiki 目录、独立的数据库。
> > 这是为了保证 PPT 知识库的纯度 —— 不混入非 PPT 数据导致推荐噪声。
> > 如果有需要可日后通过 ingest API 将 wiki-infosec 的数据作为外部上下文导入。

```

#### 4.2 CI/CD 流水线（GitHub Actions）— 当前状态：3-job 分离配置

```yaml
# .github/workflows/ci.yml — 2026-05-08 更新
name: Slydo CI
on: [push, pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install ruff black isort mypy
      - run: ruff check . && black --check . && isort --check .
      - run: mypy app/
  unit:
    runs-on: ubuntu-latest
    needs: [lint]
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_PASSWORD: test
          POSTGRES_DB: slydo_test
      qdrant:
        image: qdrant/qdrant
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: pytest tests/ --ignore=tests/test_api_integration.py -v
  integration:
    if: false  # 待 GitHub runner 能连外部服务时启用
    runs-on: ubuntu-latest
    needs: [unit]
    ...
```

> **说明：** 当前实际 CI 配置实现为 3-job 分离：lint → unit → integration（integration 暂禁）。
> unit job 在 GitHub runner 的 postgres+qdrant 容器内运行 82 个单元测试。
> integration job 因依赖真实外部服务（端口 18011 自动启动服务器），待条件成熟后启用。

#### 4.3 提交前检查清单

```
[ ] 类型注解完整（mypy --strict 通过）
[ ] 所有外部 API 调用有 @retry
[ ] 新增 API 有对应的测试
[ ] Database schema 变更使用 Alembic 迁移
[ ] 敏感配置通过环境变量注入而非硬编码
[ ] 代码有中文注释说明业务逻辑意图
[ ] PR 描述包含变更原因和影响范围
[ ] 引用了设计说明书中对应的章节号
```

---

## 第二部分：分阶段开发计划

---

### Phase A：数据基建（W1-W3，21天） ✅ 已完成

#### A1 — 项目初始化（3天） ✅

| 任务 | 产出 | 状态 |
|:---|:---|:---:|
| 初始化项目结构 | `slydo-backend/` 目录 + `pyproject.toml` + venv | ✅ |
| 初始化 git 仓库 | `git init` + `.gitignore` + 首次 commit `v0.0.1` | ✅ |
| 搭建 FastAPI 骨架 | `app/main.py` + 健康检查端点 | ✅ |
| 配置 PostgreSQL + zhparser | `database.py` + 创建数据库 `slydo` + Alembic 初始化 | ✅ |
| 部署 Qdrant 本地模式 | `qdrant_client` 初始化代码 | ✅ |
| 配置 Ollama 模型 | 验证 bge-m3 + 视觉模型 API 可达 | ✅ |
| 创建 DB schema 迁移 | 5 张表的建表脚本（Alembic revision） | ✅ |
| 验证 CI 流水线 | GitHub Actions 配置 + 首次 green build | ⬜ |

**里程碑：** `GET /health` 返回 PostgreSQL ✅ Qdrant ✅ Ollama ✅ **已通过**

#### A2 — ETL Phase 1（5天） ✅

| 任务 | 产出 | 状态 |
|:---|:---|:---:|
| `extract_slides()` 实现 | python-pptx 提取文本 | ✅ |
| `render_slides_to_images()` | LibreOffice → PDF → PNG | ✅ |
| checksum 去重逻辑 | MD5 + DB 比对 | ✅ |
| 单元测试（Phase 1/2） | 20 个测试覆盖正常解析/损坏文件/渲染/checksum/simhash | ✅（82 个单元测试，含 A2/B2/B3/D3 全模块） |
| 集成测试 | 真实 PPT 文件入库验证 | ✅（33个文档端到端验证） |

**验收标准：** `python3 etl_ingest.py test.pptx` ✅

#### A3 — ETL Phase 2（5天） ✅

| 任务 | 产出 | 状态 |
|:---|:---|:---:|
| `llm_extract_meaning_single()` | Ollama → DashScope 视觉模型调用 | ✅ |
| JSON 解析容错 | `re.search` 兜底 + 日志 | ✅ |
| `@retry` 重试装饰器 | 指数退避（3次） | ✅ |
| `TokenCounter` + 成本估算 | 入库完成后打印报告 | ✅ |
| 批处理优化 | 同一 PPT 页面合并 API 请求 | ✅（backfill_vision 独立脚本支持断点） |

**验收标准：** 单页推理返回 JSON: `{role, summary, visual_desc, tags}` ✅

**实绩：** 已完成 33 个文档 1265 页的视觉分析（DashScope qwen3-vl-flash，约2-4秒/页，总费约¥0.18）

#### A4 — ETL Phase 3 + 4（5天） ✅

| 任务 | 产出 | 状态 |
|:---|:---|:---:|
| `write_to_postgres()` | asyncpg 批量写入 slides + tags | ✅ |
| `write_to_llm_wiki()` | Markdown 文件写入 `~/.slydo/wiki/` | ✅（1299 个 Wiki 文件） |
| `embed_to_qdrant()` | BGE-M3 向量嵌入 + Qdrant upsert | ✅（1265 points） |
| Phase 5 QS 初始化 | `quality_score = 0.0` | ✅ |
| ETL 全流程集成测试 | 完整 W1-W3 流程端到端验证 | ✅（33 PPT 端到端验证） |

**里程碑：** PPT 入库成功 ✅ — 33 文档/1265 slides/1299 Wiki/1265 Qdrant points

#### A5 — 版本管理模块（3天，A4 同期并行） ✅

| 任务 | 产出 | 状态 |
|:---|:---|:---:|
| `deck_versions` 表创建 | 版本历史表 SQL + Alembic | ✅ |
| `update_deck()` 完整实现 | 旧版归档 + 新版覆盖 | ✅ |
| 源文件版本备份 | `raw/deck_<id>_v<n-1>.pptx` | ✅ |
| 版本清理 SQL + cron | 每日清理超过 2 版本的旧记录 | ✅ |
| `restore` API | `POST /api/decks/{id}/restore` | ✅ |

### Phase B：核心检索（W4-W5，14天） ✅ 已完成

#### B1 — 推荐引擎（7天） ✅

| 任务 | 产出 | 状态 |
|:---|:---|:---:|
| `recommend_slides()` 多路召回 | Qdrant 语义 + PG FTS | ✅ |
| 双路去重 | `seen_ids = set()` 过滤 | ✅ |
| `llm_rerank()` | DeepSeek API + Wiki 上下文 | ✅（含降级兜底） |
| 推荐 API 端点 | `GET /api/recommend` | ✅ |
| 场景 A（标题驱动） | 插件事件 → 后端 API | ✅ |
| 场景 C（手动搜索） | 搜索端点 + 标签筛选 | ✅ |

**里程碑：** 输入标题→返回推荐页面+LLM推荐理由 ✅

#### B2 — 单页导出（4天） ✅

| 任务 | 产出 | 状态 |
|:---|:---|:---:|
| `export_single_slide()` | python-pptx 单页导出 | ✅ |
| `GET /api/slides/{id}/export` | 返回临时文件流 | ✅ |
| VSTO 插件端调用 | `InsertFromFile` + 临时文件管理 | ✅ |

**验收标准：** API 调用返回单页 PPT，VSTO 端导入成功 ✅

#### B3 — API 补全 + 测试（3天） ✅

| 任务 | 产出 | 状态 |
|:---|:---|:---:|
| `GET /api/decks/{id}` | 文档详情 | ✅ |
| `DELETE /api/decks/{id}` | 含级联清理 | ✅ |
| `GET /api/slides/{id}` | 页面详情 | ✅ |
| 监控仪表盘 | `/dashboard` + `GET /api/monitor/stats` + `GET /api/monitor/health` | ✅ |
| API 集成测试 | 23 个测试覆盖 Deck/Slide/推荐/搜索/大纲推荐/监控/健康检查/仪表盘 | ✅（httpx + 自动服务器启动） |
| `POST /api/decks/{id}/toggle-official` | 管理员标记金牌 ⭐ 页面（`is_official = true`） | ✅ |

---

### Phase C：插件 MVP（W6-W8，21天） ✅ 已完成

#### C1 — VSTO 插件基础（7天） ✅

| 任务 | 产出 | 状态 |
|:---|:---|:---:|
| VSTO 项目初始化 | `SlydoAddIn.csproj` + Ribbon | ✅ |
| 侧边栏 Task Pane | 缩略图流式布局 | ✅ |
| 后端 API 调用封装 | `SlydoApiClient.cs` | ✅ |
| `InsertFromFile` 导入 | 一键导入后台页面 | ✅ |

**验收标准：** 侧边栏展示推荐缩略图，点击后页面导入到当前 PPT ✅

> **跨平台说明：** VSTO 插件必须在 Windows + Visual Studio 2022+ + .NET Framework 4.8+ 环境下编译

#### C2 — 完整交互体验（7天） ✅

| 任务 | 产出 | 状态 |
|:---|:---|:---:|
| 场景 A 事件监听 | `SlideSelectionChanged` → 触发推荐 | ✅ |
| 搜索面板 | 关键词输入 + 筛选下拉 | ✅ |
| 金牌标识 | 缩略图右上角 ★ 星级标注 | ⬜（QS 数据尚未充分积累） |
| 状态管理 | 加载中/空结果/错误状态 | ✅ |

**验收标准：** 新建空白页 → 自动推荐 → 选择导入 ✅

#### C3 — 插件稳定化（7天） ✅ 已完成（2026-05-10）

| 任务 | 产出 | 状态 | 备注 |
|:---|:---|:---:|:---|
| 边界情况处理 | 无标题页/艺术字标题/母版页 | ✅ | `ExtractSlideTitle()` 三级提取策略；母版/备注/浏览视图自动跳过 |
| 错误处理 | 网络异常/超时/服务不可用 | ✅ | 移除 MessageBox 弹窗，状态栏友好提示；超时 30s→10s |
| 离线缓存 | 本地缓存最近推荐结果 | ✅ | `%LOCALAPPDATA%\Slydo\cache\` JSON 缓存；失败时自动降级，显示 💾 离线缓存 标识 |
| VSTO 打包 | MSI 安装包指南 | ✅ | `VSTO-打包指南.md` 含发布向导 + WiX 两种方案 |

**里程碑：插件 MVP 可用** — 断网场景缓存 + 联网自动刷新 ✅

### Bug 修复记录（2026-05-10）

| 问题 | 根因 | 修复 |
|:---|:---|:---|
| 🔴 推荐结果默认只有 5 条 | 后端 `TOP_N=5`；前端传 `top_k` 后端用 `top_n` 参数名不匹配 | `TOP_N=5→20`；路由加 `alias="top_k"` |
| 🔴 卡片宽度不跟随侧边栏 | `ContentPresenter` 缺少 `HorizontalContentAlignment="Stretch"` | XAML 中修复 |
| 🟡 `System.Windows.Forms` vs `System.Windows.Media` 命名空间冲突 | 混合引用导致 `Brushes`/`Color`/`Cursors` 二义性 | 移除冲突 using，完全限定名引用 WinForms 类型 |
| 🟡 `Settings.ApiBaseUrl` 编译错误 | Settings.Designer.cs 未同步更新 | 改用 `ConfigurationManager.AppSettings` 读写配置 |

---

### Phase D：智能升级（W9-W12，28天） ✅ 已完成

#### D1 — 目录监控（5天） ✅

| 任务 | 产出 | 状态 |
|:---|:---|:---:|
| `PptWatcher` 实现 | watchdog 文件事件监听 | ✅（watcher.py，391行完整实现） |
| `on_created` → 增量入库 | 新文件自动触发 ETL | ✅ |
| `on_modified` → checksum 比对 | 修改文件自动更新 | ✅ |
| `on_deleted` → 级联清理 | 删除源文件清理全部关联数据 | ✅（含 Qdrant/wiki/thumbnail/源文件备份） |
| 防抖机制 | 1s 内同路径事件只触发一次 | ✅ |
| `--poll` 单次扫描模式 | 实时监控 / cron 轮询双模式 | ✅ |
| 系统服务注册 | systemd unit / Windows Service | ⬜（WSL 开发阶段先验证 Python 脚本） |

**验收标准：** 监控目录放入 PPT → 10s 内自动入库 ✅；删除源文件 → 清理 ✅

#### D2 — 场景 B 大纲推荐（7天） ✅

| 任务 | 产出 | 状态 |
|:---|:---|:---:|
| 获取 PPT 已完成页标题序列 | VSTO 端收集数据 | ✅ |
| LLM 推理 3 个潜在走向 | DeepSeek Prompt | ✅ |
| 按走向检索 + 推荐 | 多路召回 + 重排 | ✅ |
| 场景 B 完整交互 | 空白页时自动触发 | ✅ |

**验收标准：** 新建空白 PPT → 系统根据已有页面推荐 3 个方向 ✅

**测试验证（2026-05-09）：**
- 正常标题序列 → 8.3s 返回 3 路 15 页推荐（应用场景与案例/实施效果与价值/竞争对比与优势）✅
- 空标题降级 → 自动回落 3 个默认走向（解决方案概述/核心功能详解/客户案例）✅
- 带当前页（单个标题）→ 按场景推测推理，结果合理 ✅

#### D3 — QS 评分系统（6天） ✅ 全部完成，子任务拆分更新 2026-05-08

| 任务 | 产出 | 状态 | 备注 |
|:---|:---|:---:|:---|
| `usage_log` 写入 | 每次导入时记录 | ✅ | 导出 API 自动记录 |
| 每日离线 QS 计算 | cron + SQL 汇总 | ✅ | `scripts/qs_calculate.py`，公式 `QS = 0.6·min(usage/10,1) + 0.4·official` |
| 管理员手动标记 | 设置 `is_official = true` | ✅ | `POST /api/decks/{id}/toggle-official?action=slide&slide_id=...` 验证通过 |
| QS 参与排序 | `α·cosine + β·QS` 公式 | ✅ | 排序公式 `QS = 0.7·cosine + 0.3·QS_score`，LLM 重排降级时使用 |

**测试验证（2026-05-08）：**
- QS 离线计算：1265 页全部完成，Top 10 页 QS=0.060（有使用记录）✅
- 单页金牌标记 ⭐：`POST` 标记/取消 API 验证通过 ✅
- usage_log 写入：导出 API 自动记录（2 条来自 D3 测试的导出记录）✅
- 排序集成：LLM 降级时使用 `0.7·cosine + 0.3·QS` 混合排序 ✅

**设计决策：**
- QS 公式 `QS = 0.6·min(usage/10,1) + 0.4·official`：usage 封顶 10 次避免过度偏向高频页，手动金牌权重 40%
- 排序公式 `QS = 0.7·cosine + 0.3·QS_score`：只在 LLM 重排降级时使用，不干扰正常推荐流程

#### D4 — LLM Wiki 完善（5天） ✅

| 任务 | 产出 | 状态 |
|:---|:---|:---:|
| `scripts/wiki_maintenance.py` | 全库 index.md + 清理孤立 | ✅（33 个 index.md 已生成，2.4s 全库完成）|
| `index.md` 全库索引 | 统计总览 + 标签云 + 文档列表 | ✅ |
| Wiki 清理维护 | 清理 orphaned wiki + thumbnail 目录 | ✅ |

**测试验证（2026-05-09）：**
- 全量维护 33/33 个 deck 全部成功 ✅
- 全库 index.md 内容完整（33 文档/1265 页/2 次导入）✅
- 无孤立目录需要清理 ✅

**性能优化（2026-05-09）：**
- `generate_deck_index()` 循环内额外 SQL 查询（1265 次）已优化为直接从主查询获取 `id::text as slide_id`，SQL 查询数从 1266 次降至 1 次，执行时间不变（I/O 主导）。
- 修复前：每页循环内 `async with async_session_factory() as session: ...` 逐条查 ID
- 修复后：主查询增加 `id::text as slide_id`，循环内直接查字典 `usage_map`

---

### Phase E：企业集成（W13+）

| 任务 | 周期 | 依赖 |
|:---|:---|:---|
| SSO 登录（LDAP/OAuth） | 10天 | C1 |
| 部门级数据隔离 | 7天 | C1 |
| 多用户并发 | 5天 | C1 |
| Docker 容器化 | 5天 | A1 |
| 性能基准测试 + 优化 | 7天 | B1 |
| 管理后台（页面管理/Qdrant 管理） | 10天 | A4+B1 |
| 用户手册 + 管理员文档 | 5天 | 全部完成 |

---

### 里程碑总览（截止 2026-05-09）

```
v0.0.1        A1 项目骨架搭建完成 ✅
                └── 里程碑：健康检查通过 ✅

v0.1.0        A2+A3+A4+A5 ETL 全流程跑通 ✅
                └── 里程碑：33 个 PPT 入库成功（1265 页/1299 Wiki/1265 向量点）✅

v0.2.0        B1+B2+B3 核心检索完成 ✅
                └── 里程碑：输入标题→返回推荐+LLM推荐理由 ✅

v0.3.0        C1+C2+C3 插件 MVP 可用 ✅
                └── 里程碑：PPT 内可导入推荐页面 ✅
                └── 稳定化/离线缓存/打包指南 已完成 ✅

v0.4.0        D1+D2+D3+D4 智能升级完成 ✅
                └── 里程碑：目录监控 + 场景B大纲推荐 + QS评分 + Wiki维护 ✅
                └── A2（82单元测试）/ B3（23集成测试）全量覆盖 ✅
                └── CI 分离 3-job（lint/unit/integration）✅
                └── 测试状态：82 单元 + 23 集成 = 105 全过 ✅
```

---

### Phase A 任务依赖关系图（前3周详细串行）

```
A1 (3天) ─┬─→ A2 (5天) ──→ A3 (5天) ──→ A4 (5天)
           │                                     │
           └──→ A5 (3天, 与A4并行) ──────────────┘
                                                 │
                                          A3+A4 占用重叠
                                          实际 W1+W2+W3 = 21天
```

### B~E 各 Phase 串行依赖关系

```
A4 → B1 → B2 → B3 → C1 → C2 → C3 → D1 → D2 → ... → E
     │           │
     └───────────┤
     推荐引擎    单页导出
     依赖 A4     依赖 A4
```
