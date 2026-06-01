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
            this.SizeToContent = SizeToContent.WidthAndHeight;
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
            // 计算屏幕宽高
            double screenWidth = System.Windows.SystemParameters.PrimaryScreenWidth;
            double screenHeight = System.Windows.SystemParameters.PrimaryScreenHeight;

            // 预览窗口自身宽高
            double previewWidth = 274;
            double previewHeight = 270;

            // 判断侧边栏在屏幕左侧还是右侧
            // 如果侧边栏左侧空间足够（>= 预览宽度+10px），显示在左侧；否则显示在右侧
            double left;
            if (parentScreenPos.X >= previewWidth + 20)
            {
                // 左侧空间足够 → 左侧弹出
                left = parentScreenPos.X - previewWidth - 6;
            }
            else
            {
                // 左侧不够 → 右侧弹出
                left = parentScreenPos.X + parentWidth + 6;
            }

            // 边界夹紧：确保预览窗口不超出屏幕左右边界
            if (left + previewWidth > screenWidth - 10)
                left = screenWidth - previewWidth - 10;
            if (left < 5)
                left = 5;

            // 垂直居中
            double top = parentScreenPos.Y - previewHeight / 2 + 50;
            // 确保不超出屏幕顶部
            if (top < 10) top = 10;
            // 确保不超出屏幕底部
            if (top + previewHeight > screenHeight - 10)
                top = screenHeight - previewHeight - 10;

            this.Left = left;
            this.Top = top;

            if (!this.IsVisible)
            {
                this.Show();
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
