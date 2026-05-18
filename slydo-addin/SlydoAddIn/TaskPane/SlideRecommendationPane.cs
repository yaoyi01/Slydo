using System;
using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;
using SlydoAddIn.Services;

namespace SlydoAddIn.TaskPane
{
    public partial class SlideRecommendationPane : UserControl
    {
        private readonly SlydoApiClient _apiClient;
        private readonly SlideRecommendationWpf _wpfControl;
        private readonly System.Windows.Forms.Integration.ElementHost _elementHost;

        public SlideRecommendationPane()
        {
            InitializeComponent();

            _apiClient = new SlydoApiClient();
            _wpfControl = new SlideRecommendationWpf();
            _wpfControl.OnImportRequested += ImportSlide;
            // 传入 WinForms 容器引用给 WPF 控件（用于预览窗口定位）
            _wpfControl.SetParentWinFormsControl(this);

            _elementHost = new System.Windows.Forms.Integration.ElementHost
            {
                Dock = DockStyle.Fill,
                Child = _wpfControl
            };
            this.Controls.Add(_elementHost);

            // 窗口大小变化时同步 WPF 控件宽度
            this.Resize += (s, e) =>
            {
                if (_wpfControl != null && this.ClientSize.Width > 0)
                {
                    _wpfControl.Width = this.ClientSize.Width;
                    _wpfControl.UpdateLayout();
                }
            };

            // 加载后自动触发推荐
            this.Load += (s, e) => _wpfControl.TriggerRecommendation();
        }

        public void TriggerRecommendation()
        {
            _wpfControl.TriggerRecommendation();
        }

        public void UpdateCurrentTitle(string title)
        {
            _wpfControl.UpdateCurrentTitle(title);
        }

        public void TriggerOutlineRecommendation(List<string> completedTitles, string currentTitle = "")
        {
            _wpfControl.LoadOutline(completedTitles, currentTitle);
        }

        private async void ImportSlide(SlideResult slide)
        {
            try
            {
                var tempFile = await _apiClient.ExportSlideAsync(slide.SlideId, -1);

                // 记录导入行为
                _apiClient.LogUsageAsync(slide.SlideId, "import");

                var pptApp = Globals.ThisAddIn.Application;
                var activePres = pptApp.ActivePresentation;

                int targetIndex = 1;
                try
                {
                    var selection = pptApp.ActiveWindow.Selection;
                    if (selection != null && selection.Type == Microsoft.Office.Interop.PowerPoint.PpSelectionType.ppSelectionSlides)
                    {
                        var slideRange = selection.SlideRange;
                        if (slideRange != null && slideRange.Count > 0)
                        {
                            targetIndex = slideRange[1].SlideIndex;
                        }
                    }
                }
                catch { }

                activePres.Slides.InsertFromFile(tempFile, targetIndex, 1, 1);
                try { System.IO.File.Delete(tempFile); } catch { }
            }
            catch (Exception ex)
            {
                MessageBox.Show("导入失败:\n" + ex.Message, "Slydo", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        }

        public void Cleanup()
        {
            _apiClient?.Dispose();
            _wpfControl?.Cleanup();
        }
    }
}
