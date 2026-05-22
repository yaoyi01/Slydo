using System;
using System.IO;
using System.Reflection;
using System.Windows.Forms;
using Microsoft.Office.Tools;
using Office = Microsoft.Office.Core;
using SlydoAddIn.Services;

namespace SlydoAddIn
{
    public partial class ThisAddIn
    {
        private CustomTaskPane _taskPane;
        private TaskPane.SlideRecommendationPane _paneControl;

        private static string LoadApiBaseUrl()
        {
            try
            {
                var regKey = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(@"SOFTWARE\Slydo");
                if (regKey != null)
                {
                    var val = regKey.GetValue("ApiBaseUrl") as string;
                    regKey.Close();
                    if (!string.IsNullOrWhiteSpace(val))
                        return val;
                }
            }
            catch { }
            return "http://115.191.10.205";
        }

        private static void SaveApiBaseUrl(string url)
        {
            try
            {
                var regKey = Microsoft.Win32.Registry.CurrentUser.CreateSubKey(@"SOFTWARE\Slydo");
                regKey.SetValue("ApiBaseUrl", url);
                regKey.Close();
            }
            catch { }
        }

        // 后端服务地址（从注册表读取，支持运行时切换）
        public static readonly string ApiBaseUrl = LoadApiBaseUrl();
        //public static readonly string ApiBaseUrl = "https://slydo.leagsoft.com";

        private void ThisAddIn_Startup(object sender, EventArgs e)
        {
            // Step 1: 检查登录状态
            bool loggedIn = TokenManager.IsLoggedIn;
            if (!loggedIn)
            {
                ShowLoginForm();
                // 检查是否登录成功了（用户可能取消了登录）
                loggedIn = TokenManager.IsLoggedIn;
            }

            // Step 2: 初始化 Task Pane
            _paneControl = new TaskPane.SlideRecommendationPane();
            _taskPane = CustomTaskPanes.Add(_paneControl, "Slydo 知识库");

            // 设置 Task Pane 默认宽度（单位：像素）
            _taskPane.Width = 350;

            // 默认可见
            _taskPane.Visible = true;

            // 注册窗口事件
            Globals.ThisAddIn.Application.WindowSelectionChange += OnWindowSelectionChange;
            Globals.ThisAddIn.Application.SlideSelectionChanged += OnSlideSelectionChanged;

            // 首次加载自动触发推荐
            System.Windows.Forms.Timer initTimer = new System.Windows.Forms.Timer();
            initTimer.Interval = 1000; // 等待 PPT 完全加载
            initTimer.Tick += (s, args) =>
            {
                initTimer.Stop();
                _paneControl?.UpdateConnectionStatus(loggedIn);
                if (loggedIn)
                    _paneControl?.TriggerRecommendation();
            };
            initTimer.Start();
        }

        /// <summary>
        /// 弹出登录窗口
        /// </summary>
        private void ShowLoginForm()
        {
            try
            {
                using (var loginForm = new LoginForm())
                {
                    loginForm.StartPosition = FormStartPosition.CenterScreen;
                    loginForm.ShowDialog();
                }
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"[Slydo] 登录窗口异常: {ex.Message}");
            }
        }

        private void ThisAddIn_Shutdown(object sender, EventArgs e)
        {
            // 清理资源
            _paneControl?.Cleanup();
        }

        /// <summary>
        /// 窗口选择变化事件 — 用于检测当前编辑的幻灯片
        /// </summary>
        private void OnWindowSelectionChange(Microsoft.Office.Interop.PowerPoint.Selection sel)
        {
            // 场景 A: 自动推荐（由 SlideSelectionChanged 驱动）
        }

        /// <summary>
        /// 幻灯片选择变化事件 — 触发自动推荐或大纲推荐（场景 B）
        /// </summary>
        private void OnSlideSelectionChanged(Microsoft.Office.Interop.PowerPoint.SlideRange slideRange)
        {
            if (slideRange == null || slideRange.Count == 0)
                return;

            // 边界情况：非普通幻灯片视图（母版/备注/浏览模式）时 skip
            try
            {
                var viewType = Globals.ThisAddIn.Application.ActiveWindow.ViewType;
                if (viewType != Microsoft.Office.Interop.PowerPoint.PpViewType.ppViewNormal &&
                    viewType != Microsoft.Office.Interop.PowerPoint.PpViewType.ppViewOutline &&
                    viewType != Microsoft.Office.Interop.PowerPoint.PpViewType.ppViewSlide)
                    return;
            }
            catch
            {
                return; // 无活跃窗口时直接跳过
            }

            var slide = slideRange[1];
            string slideTitle = "";

            try
            {
                // 获取当前页标题（兼容多种标题形式）
                slideTitle = ExtractSlideTitle(slide);
            }
            catch
            {
                // 某些页面可能没有标题
            }

            // 判断是否是空白页（无标题）
            bool isBlank = string.IsNullOrWhiteSpace(slideTitle);

            if (isBlank)
            {
                // 场景 B：空白页 → 大纲推荐
                // 收集已完成的页面标题
                var completedTitles = new System.Collections.Generic.List<string>();
                try
                {
                    var presentation = Globals.ThisAddIn.Application.ActivePresentation;
                    if (presentation != null)
                    {
                        for (int i = 1; i <= presentation.Slides.Count; i++)
                        {
                            try
                            {
                                var s = presentation.Slides[i];
                                string t = ExtractSlideTitle(s);
                                completedTitles.Add(string.IsNullOrWhiteSpace(t) ? $"(第{i}页)" : t);
                            }
                            catch { }
                        }
                    }
                }
                catch { }

                _paneControl?.TriggerOutlineRecommendation(completedTitles, slideTitle);
            }
            else
            {
                // 场景 A：有标题 → 标题驱动推荐
                _paneControl?.UpdateCurrentTitle(slideTitle);
            }
        }

        /// <summary>
        /// 从幻灯片中提取标题，兼容普通标题框、艺术字标题、自定义占位符
        /// </summary>
        private string ExtractSlideTitle(Microsoft.Office.Interop.PowerPoint.Slide slide)
        {
            // 1. 优先使用 Shapes.Title（标准标题占位符）
            if (slide.Shapes.HasTitle != 0)
            {
                var titleShape = slide.Shapes.Title;
                if (titleShape != null && titleShape.TextFrame.HasText != 0)
                {
                    string text = titleShape.TextFrame.TextRange.Text;
                    if (!string.IsNullOrWhiteSpace(text))
                        return text.Trim();
                }
            }

            // 2. 遍历所有形状查找可能的标题（兼容艺术字、非标准标题占位符）
            try
            {
                foreach (Microsoft.Office.Interop.PowerPoint.Shape shape in slide.Shapes)
                {
                    try
                    {
                        // 跳过图片、图表等非文字形状
                        if (shape.HasTextFrame != 0 && shape.TextFrame.HasText != 0)
                        {
                            string text = shape.TextFrame.TextRange.Text;
                            if (!string.IsNullOrWhiteSpace(text))
                            {
                                text = text.Trim();
                                // 检查是否符合标题特征：短文本、第一行/位置靠上
                                if (text.Length <= 50 && text.Split('\n').Length <= 3)
                                {
                                    // 判断位置：靠上前 1/3 区域视为标题
                                    float topRatio = shape.Top / (slide.Master.Height > 0 ? slide.Master.Height : 1);
                                    if (topRatio < 0.35f)
                                        return text;
                                }
                            }
                        }
                    }
                    catch { }
                }
            }
            catch { }

            // 3. 兜底：取第一个非空文本形状的内容（避免完全无推荐）
            try
            {
                foreach (Microsoft.Office.Interop.PowerPoint.Shape shape in slide.Shapes)
                {
                    try
                    {
                        if (shape.HasTextFrame != 0 && shape.TextFrame.HasText != 0)
                        {
                            string text = shape.TextFrame.TextRange.Text;
                            if (!string.IsNullOrWhiteSpace(text))
                                return text.Trim().Substring(0, Math.Min(text.Trim().Length, 50));
                        }
                    }
                    catch { }
                }
            }
            catch { }

            return "";
        }

        /// <summary>
        /// 显示/隐藏 Task Pane（Ribbon 按钮回调）
        /// </summary>
        public void ToggleTaskPane()
        {
            if (_taskPane != null)
            {
                _taskPane.Visible = !_taskPane.Visible;
            }
        }

        #region VSTO 自动生成代码
        /// <summary>
        /// Required method for Designer support - do not modify
        /// the contents of this method with the code editor.
        /// </summary>
        private void InternalStartup()
        {
            this.Startup += new System.EventHandler(ThisAddIn_Startup);
            this.Shutdown += new System.EventHandler(ThisAddIn_Shutdown);
        }
        #endregion
    }
}
