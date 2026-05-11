# 🧠 Slydo — 企业级 PPT 智能知识库系统

> **智能推荐 · 一键导入 · 知识复用**  
> 让每一页精心设计的幻灯片都能被轻松发现和复用

---

## 📋 项目简介

Slydo 是一个面向企业级用户的 **PPT 知识库管理系统**。它将分散在企业各个角落的 PowerPoint 文档集中管理，利用 AI 语义理解和向量检索技术，帮助用户在制作新 PPT 时快速找到、预览并导入历史项目中高质量的幻灯片页。

不再"从零开始"或"翻文件夹找模板"——Slydo 让每一页精品幻灯片都被充分利用。

---

## ✨ 核心亮点

- 🚀 **一键导入** — 在 PowerPoint 侧边栏中浏览推荐结果，点击即可将目标幻灯片导入当前演示文稿
- 🔍 **语义 + 关键词混合检索** — 输入自然语言描述或关键词，AI 自动理解意图召回最匹配的幻灯片
- 🧠 **AI 驱动** — 使用 DeepSeek LLM 进行语义扩写、大纲推荐和内容评分
- 🖼️ **实时预览** — 悬停即可查看幻灯片缩略图，无需离开编辑界面
- 📂 **全格式自动入库** — PPT/PPTX 文件放入监控目录，自动触发 ETL 管道完成解析、向量化、入库
- 📡 **离线降级** — 网络异常时自动切换到本地缓存数据，保证核心功能可用
- 🏢 **企业就绪** — .NET Framework 4.8 轻量级 Agent，无需额外运行时，域策略 GPO 可批量部署

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                   PowerPoint (VSTO 插件)                      │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                 Slydo 侧边栏                           │   │
│  │  ┌─────┐  ┌──────────┐  ┌────────┐  ┌───────────┐   │   │
│  │  │ 搜索 │  │ 推荐列表 │  │ 预览窗 │  │ 大纲推荐  │   │   │
│  │  └─────┘  └──────────┘  └────────┘  └───────────┘   │   │
│  └──────────────────┬───────────────────────────────────┘   │
└──────────────────────┼──────────────────────────────────────┘
                       │ HTTPS / API
┌──────────────────────┼──────────────────────────────────────┐
│              FastAPI 后端 (Python)                           │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌─────────┐   │
│  │ 检索服务  │  │ 推荐服务  │  │ 缩略图服务  │  │ 导出服务 │   │
│  └────┬─────┘  └────┬─────┘  └─────┬──────┘  └────┬────┘   │
│       │              │              │              │         │
│  ┌────┴──────────────┴──────────────┴──────────────┴────┐   │
│  │               Qdrant 向量数据库                        │   │
│  │               PostgreSQL 元数据存储                   │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  ETL 管道（异步 Arq Worker）                         │   │
│  │  PPT → PDF → 图片 → 视觉分析 → 文本提取 → 向量化    │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

---

## 📁 项目结构

```
slydo-backend/                  # FastAPI 后端服务
├── app/
│   ├── main.py                 # 入口 + 路由注册
│   ├── config.py               # 配置管理
│   ├── database.py             # PostgreSQL 数据库连接
│   ├── qdrant.py               # Qdrant 向量数据库
│   ├── routers/                # API 路由
│   │   ├── recommend.py        # 语义推荐接口
│   │   ├── export.py           # 单页 PPTX 导出
│   │   ├── thumbnail.py        # 缩略图服务
│   │   ├── deck.py/slide.py    # 文档/页面管理
│   │   ├── monitor.py          # 系统监控仪表盘
│   │   └── version.py          # 版本信息
│   └── services/
│       ├── recommend.py        # 推荐核心逻辑（LLM 重排 + 向量检索）
│       ├── export.py           # 单页 PPTX 导出实现
│       └── etl/                # ETL 管道
│           ├── phase1_extract.py   # PPT → 文本/图片提取
│           ├── phase2_vision.py    # 视觉模型分析
│           └── phase3_store.py     # 结果入库
├── .env.example                # 环境变量模板
└── requirements.txt

slydo-addin/                    # PowerPoint VSTO 插件（C# .NET Framework 4.8）
└── SlydoAddIn/
    ├── ThisAddIn.cs            # VSTO 入口 + 事件驱动
    ├── Services/
    │   ├── SlydoApiClient.cs   # API 客户端（含离线缓存降级）
    │   └── SlydoModels.cs      # 数据模型定义
    └── TaskPane/
        ├── SlideRecommendationWpf.xaml  # 主侧边栏
        ├── SlideCardWpf.xaml            # 推荐卡片
        ├── SlidePreviewWpf.xaml         # 悬浮预览窗
        └── SlideRecommendationPane.cs   # WinForms 包装层
```

---

## 🔧 技术栈

| 组件 | 选型 | 理由 |
|------|------|------|
| **后端框架** | Python FastAPI | 异步高性能，AI 库生态丰富 |
| **向量数据库** | Qdrant | HNSW 索引，本地无 Docker 依赖，与 Postgres 互补 |
| **关系数据库** | PostgreSQL 16 | 元数据/使用日志持久化 |
| **LLM 重排** | DeepSeek V4 Flash API | 语义理解准确，低延迟，低成本 |
| **视觉模型** | Qwen3-VL (本地 Ollama) | PPT 图片/图表/SmartArt 视觉描述 |
| **消息队列** | Redis + Arq | 轻量级异步任务 |
| **VSTO 插件** | C# .NET Framework 4.8 | 最低终端要求（Windows 7+ 原生支持） |

---

## 🚀 快速开始

### 后端

```bash
cd slydo-backend

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填写 DEEPSEEK_API_KEY 和 DATABASE_URL

# 启动服务
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

### VSTO 插件（Windows + Visual Studio 2022）

1. 打开 `slydo-addin/SlydoAddIn.sln`
2. 按 F5 编译运行 → PowerPoint 自动打开 → 右侧出现 Slydo 侧边栏
3. 侧边栏 ⚙️ 按钮可配置后端地址（默认 `http://localhost:8001`）

---

## 📡 API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/recommend/slides?q=keyword&top_k=20` | 语义推荐 |
| GET | `/api/v1/recommend/export?slide_id=xxx` | 导出单页 PPTX |
| GET | `/api/v1/thumbnails/{slide_id}` | 获取缩略图 |
| GET | `/health` | 健康检查 |
| GET | `/dashboard` | 监控仪表盘 |

---

## 🗺️ 开发路线图

| 阶段 | 内容 | 状态 |
|------|------|------|
| **C1 (MVP)** | 基础推荐 + 搜索 + 缩略图预览 | ✅ 完成 |
| **C2 (增强)** | 卡片布局 + 悬浮预览 + 搜索/设置按钮 | ✅ 完成 |
| **C3 (稳定)** | 边界情况处理 + 错误处理 + 离线缓存 + 打包指南 | ✅ 完成 |
| **C4 (扩展)** | 监控仪表盘 + 性能优化 | ⏸️ 待启动 |

---

## 📄 许可

本项目为内部使用，仅供联软科技及其授权方使用。
