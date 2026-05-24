; Slydo VSTO 插件安装程序
; 用法：
;   1. 在 VS 中右键 SlydoAddIn → 发布 → 发布到 D:\SlydoInstaller\
;   2. 将此脚本放入 Inno Setup，Source 路径指向 D:\SlydoInstaller\
;   3. 编译生成 SlydoSetup.exe

#define MyAppName "Slydo 知识库助手"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Slydo"
#define MyAppURL "http://115.191.10.205"
#define MyAppExeName "setup.exe"

[Setup]
AppId={{F8C3B1A7-9D4E-4C2E-8E6A-5F1B3D7C9A0E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Slydo
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; 输出文件
OutputDir=.
OutputBaseFilename=SlydoSetup
; 压缩与安装风格
Compression=lzma
SolidCompression=yes
DisableWelcomePage=no
DisableReadyPage=no
; 需要管理员权限（VSTO 注册需要）
PrivilegesRequired=admin
; 关闭杀软误报 - 数字签名（如有证书可加）
; SignTool=signtool

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

; =============================================
; 文件列表 — 指向你的 ClickOnce 发布目录
; 请根据实际发布目录修改 Source 路径
; =============================================
[Files]
; 根目录文件
Source: "C:\Users\kiven\Documents\个人知识库\Coding\Slydo\publish\setup.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "C:\Users\kiven\Documents\个人知识库\Coding\Slydo\publish\*.vsto"; DestDir: "{app}"; Flags: ignoreversion

; Application Files 子目录（需递归）
Source: "C:\Users\kiven\Documents\个人知识库\Coding\Slydo\publish\Application Files\*"; DestDir: "{app}\Application Files"; Flags: ignoreversion createallsubdirs recursesubdirs

; =============================================
; 注册表 — 注册 VSTO 加载项到 PowerPoint
; =============================================
[Registry]
; 当前用户级别注册（推荐，不需要每台机器）
Root: HKCU; Subkey: "Software\Microsoft\Office\PowerPoint\Addins\SlydoAddIn.Connect"; ValueType: string; ValueName: "Description"; ValueData: "Slydo PPT 知识库助手"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Office\PowerPoint\Addins\SlydoAddIn.Connect"; ValueType: string; ValueName: "FriendlyName"; ValueData: "Slydo 知识库"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Office\PowerPoint\Addins\SlydoAddIn.Connect"; ValueType: dword; ValueName: "LoadBehavior"; ValueData: "3"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Office\PowerPoint\Addins\SlydoAddIn.Connect"; ValueType: string; ValueName: "Manifest"; ValueData: "{app}\SlydoAddIn.vsto|vstolocal"; Flags: uninsdeletekey

; Slydo 配置（默认 API 地址）
Root: HKCU; Subkey: "Software\Slydo"; ValueType: string; ValueName: "ApiBaseUrl"; ValueData: "http://115.191.10.205"; Flags: uninsdeletekey

; =============================================
; 卸载时清理
; =============================================
[UninstallRun]
Filename: "{localappdata}\assembly\dl3"; Parameters: "/q /s"; Flags: runhidden

; =============================================
; 安装完成后提示
; =============================================
[Run]
Filename: "{app}\setup.exe"; Description: "安装 Slydo 加载项到 PowerPoint"; Flags: postinstall nowait skipifsilent shellexec

[Code]
function InitializeSetup: Boolean;
begin
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // 安装完成后在桌面创建快捷方式（可选）
  end;
end;
