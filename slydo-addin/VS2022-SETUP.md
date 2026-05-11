# Slydo VSTO 插件 — VS 2022 开发环境说明

> 本项目已从 VS 2026 迁移到 **VS 2022**，VS 2022 对 VSTO 的支持最稳定。

## 前提条件

1. **Visual Studio 2022**（任意版本：Community / Professional / Enterprise）
2. 安装时勾选的工作负载：
   - **.NET 桌面开发**（✅ 必须）
   - **Office/SharePoint 开发**（✅ 必须 — 提供 VSTO 模板支持）

## 项目位置

```
C:\Users\kiven\Documents\个人知识库\Coding\Slydo\
├── slydo-backend\       ← FastAPI 后端（WSL 侧）
├── slydo-addin\         ← VSTO 插件项目
│   ├── SlydoAddIn.sln
│   └── SlydoAddIn\
│       ├── SlydoAddIn.csproj
│       ├── ThisAddIn.cs            ← 插件入口（业务逻辑）
│       ├── ThisAddIn.Designer.cs   ← VS 自动生成
│       ├── Services\
│       │   ├── SlydoApiClient.cs   ← API 客户端
│       │   └── SlydoModels.cs      ← JSON 模型
│       └── TaskPane\
│           └── SlideRecommendationPane.cs ← WinForms 侧边栏
```

## 打开项目

双击 `slydo-addin\SlydoAddIn.sln` 即可。

## 编译与调试

| 操作 | 快捷键 |
|------|--------|
| 编译 | `Ctrl + Shift + B` |
| 调试启动 | `F5`（自动打开 PowerPoint） |

## 后端服务

插件连接的后端地址：`http://localhost:8001`

> ⚠️ 8000 端口已被 F-IDES Docker 容器占用，故Slydo后端使用 **8001** 端口。

### 启动后端（WSL 终端）

```bash
cd /mnt/c/Users/kiven/Documents/个人知识库/Coding/Slydo/slydo-backend/
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

## 项目文件说明

### 后端（FastAPI + PostgreSQL + Qdrant）

- `app/main.py` — 入口，路由注册
- `app/routers/` — API 路由
  - `recommend.py` — 推荐（`/api/recommend` + `/api/v1/recommend/slides`）
  - `export.py` — 单页导出（`/api/slides/{id}/export` + `/api/v1/recommend/export`）
  - `deck.py` / `slide.py` / `version.py` — CRUD
- `app/services/` — 核心逻辑
  - `recommend.py` — 多路召回（语义+关键词）+ LLM 重排
  - `export.py` — ZIP 级 PPTX 单页裁剪

### VSTO 插件

- `ThisAddIn.cs` — 启动时创建侧边栏 TaskPane，注册 PowerPoint 事件
- `TaskPane/SlideRecommendationPane.cs` — 纯 WinForms 侧边栏
  - 自定义绘制推荐项（标题、摘要、匹配度）
  - `UI()` 辅助方法确保跨线程 UI 操作安全
- `Services/SlydoApiClient.cs` — 调用后端 API（推荐 + 导出）
- `Services/SlydoModels.cs` — JSON 反序列化模型（`[JsonProperty]` 映射）

## 已知限制

- 后端端口 8001（非默认 8000），因 8000 被 F-IDES Docker 占用
- 缩略图预览暂未实现（后端需改造缩略图生成流水线）
- 侧边栏暂无搜索输入框（当前用 PowerPoint 选中的页面标题自动触发搜索）

## 常见问题

### Q: 启动报 404
A: 确认后端已启动，并且端口是 8001 不是 8000。
```bash
curl http://localhost:8001/health
```

### Q: 按钮显示异常
A: 按 `Ctrl + Shift + B` 重新编译。VSTO TaskPane 的按钮使用 `FlatStyle.Standard` 系统样式。

### Q: "不兼容，该应用程序未安装"
A: 确认 VS 2022 已安装 **"Office/SharePoint 开发"** 工作负载。如仍不行，在 VS 中直接打开 `.csproj` 文件（不要走 `.sln`）。
