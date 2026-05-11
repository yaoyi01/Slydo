# Slydo VSTO Add-In

PPT 知识管理系统客户端插件。

## 开发环境要求

| 依赖 | 最低版本 | 说明 |
|:--|:--:|:--|
| Visual Studio | 2022+ | 社区版/专业版均可 |
| .NET Framework | 4.8 SDK | Windows 自动更新可获取 |
| Office | 2019+ / 365 | PowerPoint 必需 |
| VSTO 运行时 | 最新版 | 随 Office 安装 |

## 编译步骤

1. **克隆代码**（Windows 侧）

```bash
git clone <repo-url>
cd slydo-addin
```

2. **用 Visual Studio 打开**

双击 `SlydoAddIn/SlydoAddIn.csproj` 或在 VS 中选"打开项目/解决方案"。

3. **配置后端地址**

在 `ThisAddIn.cs` 中修改 `ApiBaseUrl`：

```csharp
// 开发环境
public static readonly string ApiBaseUrl = "http://localhost:8000";

// 生产环境（部署后改为实际的服务器地址）
// public static readonly string ApiBaseUrl = "https://slydo.example.com";
```

4. **编译**

- 菜单栏 → 生成 → 生成解决方案 (F6)
- 输出目录：`SlydoAddIn/bin/Debug/`

5. **运行调试**

- 按 F5 自动启动 PowerPoint 并加载插件
- 在 PPT 的 "Slydo 知识库" 选项卡中操作

## 项目结构

```
slydo-addin/
├── SlydoAddIn/
│   ├── SlydoAddIn.csproj        # 项目文件
│   ├── ThisAddIn.cs              # 插件入口 + 生命周期
│   ├── ThisAddIn.Designer.cs     # 设计器代码
│   ├── Ribbon.cs                 # Ribbon 工具栏逻辑
│   ├── Ribbon.xml                # Ribbon UI 定义
│   ├── Services/
│   │   ├── SlydoApiClient.cs     # 后端 API 封装
│   │   └── SlydoModels.cs        # JSON 数据模型
│   ├── TaskPane/
│   │   ├── SlideRecommendationPane.xaml      # WPF 面板 UI
│   │   ├── SlideRecommendationPane.xaml.cs   # 面板逻辑
│   │   └── SlideViewModel.cs                # 数据绑定模型
│   ├── Properties/
│   │   ├── AssemblyInfo.cs
│   │   ├── Resources.resx
│   │   └── Resources.Designer.cs
│   └── Resources/                # 图标资源
│       ├── logo.png
│       ├── search.png
│       ├── refresh.png
│       └── star.png
└── README.md
```

## 与后端 API 对接

插件依赖 Slydo 后端服务，请确保后端已启动：

```bash
cd slydo-backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

后端 API 参考：

| 接口 | 方法 | 用途 |
|:--|:--:|:--|
| `/api/recommend?title=X` | GET | 场景 A：按标题推荐 |
| `/api/recommend?keywords=X` | GET | 场景 C：按关键词搜索 |
| `/api/slides/{id}` | GET | 页面详情 |
| `/api/slides/{id}/export` | GET | 下载单页 PPTX |
| `/api/thumbnails/{slide_id}.png` | GET | 缩略图 |

## 发布安装包

1. 在 VS 中右键项目 → 属性 → 发布
2. 选择 ClickOnce 发布方式
3. 配置签名证书（可用测试证书）
4. 生成安装包，最终用户双击 setup.exe 安装
