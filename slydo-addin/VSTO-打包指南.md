# Slydo VSTO 插件 — MSI 打包指南

## 服务器地址配置

插件安装后，侧边栏右上角的 **⚙️** 按钮可以配置后端地址：

1. 打开 PowerPoint → Slydo 侧边栏
2. 点击右上角 ⚙️ 齿轮图标
3. 在弹出的对话框中输入后端服务器地址
4. 保存后重新搜索即可

**默认地址：** `http://localhost:8001`（开发环境）
**生产环境示例：** `http://192.168.1.100:8001` 或 `https://slydo.leagsoft.com`

> 配置保存在 `%LOCALAPPDATA%\SlydoAddIn\...\user.config` 中，卸载插件后自动清除。

---

## 方法一：VS 2022 发布向导（推荐）

1. **打开项目** — VS 2022 打开 `slydo-addin/SlydoAddIn.sln`
2. **切换 Release** — 工具栏从 Debug 切换到 **Release**
3. **生成 → 发布 SlydoAddIn**
   - 右键 SlydoAddIn 项目 → **发布**
   - 发布位置选本地文件夹（如 `C:\Slydo\publish\`）
   - 安装 URL 和更新路径设为空（本地部署）
4. **发布完成后**，在输出目录找到 `SlydoAddIn.vsto` + `setup.exe`

### 部署到其他电脑

1. 将 `publish\` 完整目录拷贝到目标电脑
2. 以管理员身份运行 `setup.exe`
3. 安装前请确保目标电脑已安装：
   - .NET Framework 4.7.2 或更高
   - Microsoft Visual Studio 2010 Tools for Office Runtime
   - Microsoft PowerPoint 2016/2019/Office 365
4. 安装后 ⚙️ 配置对应的后端服务地址

---

## 方法二：WiX Toolset（高级，更专业的 MSI）

如需要纯 MSI 安装包（不带 VSTO 引导程序），可以用 WiX：

### 准备工作

1. **安装 WiX Toolset**
   - 下载安装：[https://wixtoolset.org/](https://wixtoolset.org/)
   - 或 VS 2022 → 扩展 → 管理扩展 → 搜索 "WiX Toolset"

2. **在解决方案中新建 WiX 安装项目**
   - 右键解决方案 → 添加 → 新建项目 → 搜索 "WiX"
   - 选 **Setup Project** 模板

### WiX 脚本示例

创建 `Product.wxs`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="*" Name="SlydoAddIn" Language="1033" Version="1.0.0.0" 
           Manufacturer="Leagsoft" UpgradeCode="YOUR-GUID-HERE">
    <Package InstallerVersion="200" Compressed="yes" InstallScope="perMachine" />
    
    <MajorUpgrade DowngradeErrorMessage="A newer version of [ProductName] is already installed." />
    <MediaTemplate EmbedCab="yes" />
    
    <Feature Id="ProductFeature" Title="SlydoAddIn" Level="1">
      <ComponentGroupRef Id="ProductComponents" />
    </Feature>
    
    <!-- 注册为 VSTO 加载项 -->
    <RegistryValue Root="HKLM" Key="SOFTWARE\Microsoft\Office\PowerPoint\AddIns\SlydoAddIn"
                   Name="Manifest" Value="[INSTALLDIR]SlydoAddIn.vsto" Type="string" />
    <RegistryValue Root="HKLM" Key="SOFTWARE\Microsoft\Office\PowerPoint\AddIns\SlydoAddIn"
                   Name="LoadBehavior" Value="3" Type="integer" />
    <RegistryValue Root="HKLM" Key="SOFTWARE\Microsoft\Office\PowerPoint\AddIns\SlydoAddIn"
                   Name="FriendlyName" Value="Slydo 知识库" Type="string" />
    <RegistryValue Root="HKLM" Key="SOFTWARE\Microsoft\Office\PowerPoint\AddIns\SlydoAddIn"
                   Name="Description" Value="企业级智能 PPT 知识库系统" Type="string" />
  </Product>

  <Fragment>
    <Directory Id="TARGETDIR" Name="SourceDir">
      <Directory Id="ProgramFiles64Folder">
        <Directory Id="INSTALLDIR" Name="SlydoAddIn" />
      </Directory>
    </Directory>
  </Fragment>

  <Fragment>
    <ComponentGroup Id="ProductComponents" Directory="INSTALLDIR">
      <Component Id="SlydoAddIn.dll" Guid="YOUR-GUID">
        <File Id="SlydoAddIn.dll" Source="$(var.ReleaseDir)SlydoAddIn.dll" KeyPath="yes" />
      </Component>
      <Component Id="SlydoAddIn.dll.manifest" Guid="YOUR-GUID">
        <File Id="SlydoAddIn.dll.manifest" Source="$(var.ReleaseDir)SlydoAddIn.dll.manifest" />
      </Component>
      <Component Id="SlydoAddIn.vsto" Guid="YOUR-GUID">
        <File Id="SlydoAddIn.vsto" Source="$(var.ReleaseDir)SlydoAddIn.vsto" KeyPath="yes" />
      </Component>
      <Component Id="Newtonsoft.Json.dll" Guid="YOUR-GUID">
        <File Id="Newtonsoft.Json.dll" Source="$(var.ReleaseDir)Newtonsoft.Json.dll" />
      </Component>
    </ComponentGroup>
  </Fragment>
</Wix>
```

### WiX 编译

1. 将 WiX 安装项目设为启动项目
2. Ctrl+Shift+B 编译
3. 输出 `SlydoAddIn.msi`

---

## 先决条件分发

部署时需要确保目标电脑安装了以下组件（可与 MSI 一同打包）：

| 组件 | 下载地址 |
|------|---------|
| .NET Framework 4.7.2 | https://dotnet.microsoft.com/download/dotnet-framework/net472 |
| VSTO Runtime | https://www.microsoft.com/en-us/download/details.aspx?id=48217 |
| PowerPoint 2016+ | Office 安装包自备 |

---

## 注意事项

- VSTO 插件需要 **管理员权限** 才能安装（注册 COM 组件）
- 安装后首次启动 PowerPoint 时可能需要 **信任加载项**
- VSTO 的清单签名证书在 Release 模式下需替换为正式证书（避免安全警告）
- 生产环境部署前请通过 ⚙️ 将 `ApiBaseUrl` 改为正式服务器地址
- 配置保存在用户目录，卸载后自动清除
