# 📊 Slydo — 企业级 PPT 智能知识库系统

> **智能推荐 + 语义检索 + VSTO 插件** — 让每一次幻灯片制作都有历史可依

Slydo 是一个企业级 PPT 知识管理系统，自动提取企业已有 PPT 中的内容、语义和视觉特征，构建可搜索的知识库。通过 PowerPoint VSTO 插件，用户无需离开编辑界面即可获取历史最佳页面推荐，告别「每次写 PPT 都从零开始」。

---

## 🎯 核心亮点

- **🔍 多路召回 + LLM 重排** — Qdrant 语义搜索 + PostgreSQL 全文搜索 + DeepSeek API 逻辑重排，精准推荐历史页面
- **🖥️ PowerPoint 原生集成** — VSTO 插件，侧边栏实时推荐，一键导出页面到当前编辑文档
- **🖼️ 多模态理解** — 使用 Qwen3-VL 视觉模型自动分析每页 PPT 的语义角色和含义
- **📦 自动化 ETL 管线** — PPT 文档监控 → 文本提取 → 视觉分析 → 向量化 → 入库，全自动完成
- **🧠 LLM Wiki** — 每页 PPT 生成结构化 Markdown 笔记（含义摘要、语义标签、适用场景），支持人工修正

---

## 📱 客户端（PowerPoint VSTO 插件）

当用户编辑 PPT 时，Slydo VSTO 插件在 PowerPoint 右侧显示推荐面板：

| 功能 | 说明 |
|------|------|
| **智能推荐** | 根据当前页面标题/内容，自动推荐知识库中最匹配的历史页面 |
| **手动搜索** | 关键词搜索整个知识库 |
| **大纲推理** | 基于已完成页面序列，AI 推测下一步逻辑走向并推荐素材 |
| **一键导入** | 点击推荐页面即可复制到当前编辑的 PPT（支持跨文档） |
| **缩略图预览** | 鼠标悬停查看大图预览，快速筛选 |
| **后端配置** | 设置按钮可切换后端服务地址（注册表持久化） |

**技术栈：** C# / .NET Framework 4.7.2, WPF, VSTO, XML DOM

---

## 🖥️ 服务端（FastAPI + PostgreSQL + Qdrant）

### 推荐引擎

```
用户查询 / 当前页面标题
        │
        ▼
  ┌─────────────────────┐
  │  Step 1: 语义召回   │ ← Qdrant 向量搜索 (BGE-M3 1024维)
  └────────┬────────────┘
           ▼
  ┌─────────────────────┐
  │  Step 2: 关键词召回 │ ← PostgreSQL ILIKE 模糊匹配
  └────────┬────────────┘
           ▼
  ┌─────────────────────┐
  │  Step 3: 双路去重   │ ← 按 deck_id + slide_index 去重
  └────────┬────────────┘
           ▼
  ┌─────────────────────┐
  │  Step 4: LLM 重排   │ ← DeepSeek API 结合 Wiki 上下文
  └────────┬────────────┘
           ▼
  ┌─────────────────────┐
  │  Step 5: Top-N 返回 │ ← 含推荐理由
  └─────────────────────┘
```

### ETL 管线

```
PPT 文件
   │
   ▼
Phase1 [提取+渲染]  →  文本提取 (python-pptx) + PNG 缩略图 (LibreOffice)
   │
   ▼
Phase2 [视觉分析]   →  Qwen3-VL 多模态分析（语义角色/摘要/标签）
   │
   ▼
Phase3 [结构化存储]  →  PostgreSQL + LLM Wiki Markdown
   │
   ▼
Phase4 [向量嵌入]    →  BGE-M3 嵌入 → Qdrant 向量数据库
   │
   ▼
Phase5 [质量评分]    →  QS 评分初始化（含重复检测）
```

### API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查（PG + Qdrant 状态） |
| POST | `/api/v1/recommend/slides` | 智能推荐（标题/关键词/场景） |
| POST | `/api/v1/recommend/outline` | 大纲推理推荐 |
| GET | `/api/v1/recommend/export` | 导出推荐页面到当前 PPT |
| GET | `/api/v1/thumbnails/{slide_id}` | 获取缩略图 |
| POST | `/api/v1/decks` | 创建/更新文档库 |
| POST | `/api/v1/slides/search` | 幻灯片检索 |
| GET | `/dashboard` | 系统监控仪表盘 |
| GET | `/api/monitor/health` | 模块健康检测 |

---

## 📁 项目结构

```
slydo/
├── slydo-backend/          # FastAPI 后端
│   ├── app/
│   │   ├── main.py          # 入口 + 路由注册
│   │   ├── config.py        # 配置（.env 文件）
│   │   ├── database.py      # PostgreSQL (asyncpg + SQLAlchemy)
│   │   ├── qdrant.py        # Qdrant 向量数据库客户端
│   │   ├── models/          # SQLAlchemy ORM 模型
│   │   ├── routers/         # API 路由
│   │   │   ├── recommend.py # 推荐引擎
│   │   │   ├── export.py    # 页面导出
│   │   │   ├── deck.py      # 文档库管理
│   │   │   ├── slide.py     # 幻灯片检索
│   │   │   ├── thumbnail.py # 缩略图服务
│   │   │   └── monitor.py   # 系统监控
│   │   ├── services/
│   │   │   ├── recommend.py # 推荐引擎核心
│   │   │   ├── export.py    # 导出服务
│   │   │   └── etl/         # ETL 管线（4个阶段）
│   │   └── utils/
│   │       ├── llm.py       # DeepSeek API 调用
│   │       ├── vision.py    # Qwen3-VL 视觉分析
│   │       └── retry.py     # 重试工具
│   ├── etl_ingest.py        # ETL 入库入口
│   ├── watcher.py           # 目录监控脚本
│   └── scripts/             # 运维脚本
│
├── slydo-addin/SlydoAddIn/  # VSTO PowerPoint 插件
│   ├── ThisAddIn.cs         # 插件入口 + 后端地址管理
│   ├── TaskPane/            # 侧边栏 UI
│   │   ├── SlideRecommendationWpf.xaml  # 推荐面板
│   │   ├── SlideCardWpf.xaml            # 卡片控件
│   │   └── SlidePreviewWpf.xaml         # 预览控件
│   └── Services/
│       ├── SlydoApiClient.cs # 后端 API 客户端
│       └── SlydoModels.cs    # 数据模型
│
└── slydo-watch/             # PPT 目录监控
```

---

## 🚀 快速开始

### 前置条件

- **Python 3.11+**（后端运行环境）
- **PostgreSQL 16**（含 pgvector 扩展）
- **Qdrant**（向量数据库，推荐本地模式）
- **LibreOffice**（用于 PPT 渲染缩略图）
- **Ollama**（可选，用于本地视觉分析 qwen3-vl-fast:8b）
- **DeepSeek API Key**（推荐引擎 LLM 重排）

### 后端启动

```bash
# 1. 配置环境变量
cd slydo-backend
cp .env.example .env
# 编辑 .env，填入 DeepSeek API Key 和数据库连接

# 2. 安装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. 初始化数据库
python3 -c "import asyncio; from app.database import init_db; asyncio.run(init_db())"

# 4. 启动服务
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

### VSTO 插件编译（Windows + Visual Studio 2022）

```bash
# 在 Windows 上打开：
# slydo-addin/SlydoAddIn/SlydoAddIn.csproj
# 按 F5 编译并启动 PowerPoint
# 右侧出现 "Slydo 知识库" 侧边栏即成功
```

### PPT 入库

```bash
# 单文件入库
python3 etl_ingest.py path/to/your.pptx

# 批量入库（目录下所有 PPT）
python3 etl_ingest.py /path/to/ppt/directory/
```

---

## ⚙️ 配置说明

后端配置通过 `.env` 文件（参考 `.env.example`）：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key | — |
| `DEEPSEEK_BASE_URL` | DeepSeek API 地址 | `https://api.deepseek.com/v1` |
| `OLLAMA_BASE_URL` | Ollama 服务地址 | `http://localhost:11434` |
| `OLLAMA_VISION_MODEL` | 视觉分析模型 | `qwen3-vl-fast:8b` |
| `DATABASE_URL` | PostgreSQL 连接串 | — |
| `QDRANT_URL` | Qdrant 服务地址（留空=本地文件模式） | — |
| `SLYDO_WIKI_PATH` | LLM Wiki 存储路径 | `~/.slydo/wiki/` |

---

## 🏗️ 架构设计思路

**为什么用多路召回 + LLM 重排而不是单路向量搜索？**

PPT 页面包含丰富的结构化信息（标题层级、语义角色、视觉元素），单一向量搜索难以捕获所有维度。Slydo 采用**语义搜索 + 关键词搜索 + LLM 逻辑重排**的三层架构：

| 策略 | 解决的问题 | 技术选型 |
|------|-----------|---------|
| 语义搜索 | 找到"概念相近"的页面 | Qdrant + BGE-M3 1024维 |
| 关键词搜索 | 精确匹配专有名词/编号 | PostgreSQL ILIKE |
| LLM 重排 | 理解业务逻辑和上下文关系 | DeepSeek API + Wiki 知识 |

**为什么用 LLM Wiki 而不是只存数据库？**

每页 PPT 经过视觉模型分析后，生成结构化 Markdown 笔记（包含含义摘要、语义标签、适用场景）。这些笔记可以作为 LLM 重排的上下文知识，也可以人工编辑修正，形成持续优化的知识库。

**为什么 VSTO 插件用 WPF 而不是 WinForms？**

VSTO 的 CustomTaskPane 原生支持 WinForms，但 WPF 在布局灵活性（自适应缩放、动画、视觉特效）和数据绑定（MVVM 模式）上有显著优势。通过 `ElementHost` 实现 WPF 控件嵌入 VSTO TaskPane。

---

## 📌 已知限制

- **缩略图渲染：** LibreOffice 会跳过部分复杂 SmartArt/嵌入 OLE 的页面，缩略图数量可能少于实际页数（覆盖率约 90-99%）
- **视觉分析速度：** Qwen3-VL 在 WSL + Ollama 环境下每图约 60-120s，批量入库耗时较长
- **iLink 媒体推送：** 微信 WeChat 平台的语音/文件推送功能存在跨事件循环问题，目前仅文字消息稳定

---

## 🛣️ 开发路线

- [x] 基础 ETL 管线（文本提取 + 缩略图渲染 + 入库）
- [x] 向量语义搜索 + 关键词搜索
- [x] DeepSeek LLM 逻辑重排
- [x] PowerPoint VSTO 插件（推荐面板 + 一键导入）
- [x] 视觉模型分析（Qwen3-VL 语义角色/摘要/标签）
- [x] LLM Wiki 结构化笔记
- [x] 目录监控自动入库
- [x] 质量评分系统（QS）
- [ ] Windows COM 对象补充缩略图（替代 LibreOffice 渲染限制）
- [ ] PDF 导入支持
- [ ] Web 管理后台
- [ ] 团队协作（多用户知识库共享）
