using System;
using System.Drawing;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using SlydoAddIn.Services;
using Color = System.Windows.Media.Color;

namespace SlydoAddIn.TaskPane
{
    public partial class SlidePreviewWpf : Window
    {
        public SlidePreviewWpf()
        {
            InitializeComponent();
            this.Deactivated += (s, e) => this.Hide();
            this.ShowInTaskbar = false;
        }

        public void UpdatePreview(SlideResult slide, ImageSource thumbnail)
        {
            if (slide == null) return;

            if (thumbnail != null)
                PreviewThumb.Source = thumbnail;

            TitleText.Text = slide.DeckName ?? "未命名";
            DescText.Text = slide.Summary ?? "";

            int match = (int)(slide.Score * 100);
            MatchText.Text = $"{match}% 匹配";
            MatchText.Foreground = match >= 70
                ? new SolidColorBrush(Color.FromRgb(0, 153, 0))
                : match >= 50
                    ? new SolidColorBrush(Color.FromRgb(200, 150, 0))
                    : new SolidColorBrush(Color.FromRgb(200, 50, 50));

            bool gold = slide.LlmScore >= 8;
            TagText.Text = gold ? "⭐ 金牌" : "推荐";
            TagBorder.Background = gold
                ? new SolidColorBrush(Color.FromRgb(255, 248, 225))
                : new SolidColorBrush(Color.FromRgb(245, 245, 245));
            TagText.Foreground = gold
                ? new SolidColorBrush(Color.FromRgb(180, 130, 0))
                : new SolidColorBrush(Color.FromRgb(153, 153, 153));
            TagBorder.BorderBrush = gold
                ? new SolidColorBrush(Color.FromRgb(255, 224, 130))
                : new SolidColorBrush(Color.FromRgb(224, 224, 224));

            SourceText.Text = slide.DeckName ?? "";
        }

        public void ShowPreview(System.Windows.Point parentScreenPos, double parentWidth)
        {
            // 在侧边栏左侧显示预览
            this.Left = parentScreenPos.X - 274;
            this.Top = parentScreenPos.Y + 10;

            if (!this.IsVisible)
            {
                this.Show();
            }
            else
            {
                // 已经显示，只更新位置
                this.Left = parentScreenPos.X - 274;
                this.Top = parentScreenPos.Y + 10;
            }
            this.Activate();
            this.Topmost = true;
        }

        public void ShowPreviewAt(System.Windows.Point screenPosition)
        {
            this.Left = screenPosition.X;
            this.Top = screenPosition.Y;

            if (!this.IsVisible)
            {
                this.Show();
            }
            this.Activate();
            this.Topmost = true;
        }
    }
}
