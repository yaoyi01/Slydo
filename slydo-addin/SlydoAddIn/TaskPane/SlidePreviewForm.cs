using System;
using System.Drawing;
using System.Windows.Forms;
using SlydoAddIn.Services;

namespace SlydoAddIn.TaskPane
{
    /// <summary>
    /// 悬浮预览浮窗 — 亮色主题
    /// 鼠标悬停推荐卡片时弹出放大缩略图预览
    /// </summary>
    public class SlidePreviewForm : Form
    {
        private PictureBox _previewThumb;
        private Label _titleLabel;
        private Label _descLabel;
        private Label _matchLabel;
        private Label _tagLabel;
        private Label _sourceLabel;
        private Panel _infoPanel;

        private const int PreviewWidth = 270;
        private const int PreviewThumbHeight = 152; // 270 * 9/16 = 152

        // ── 亮色主题 ──
        private static readonly Color FormBg = Color.White;
        private static readonly Color BorderClr = Color.FromArgb(220, 222, 228);
        private static readonly Color TextPrimary = Color.FromArgb(33, 33, 33);
        private static readonly Color TextSecondary = Color.FromArgb(102, 102, 102);
        private static readonly Color TextMuted = Color.FromArgb(170, 170, 170);
        private static readonly Color AccentClr = Color.FromArgb(108, 99, 255);
        private static readonly Color MatchGreen = Color.FromArgb(0, 150, 0);
        private static readonly Color MatchYellow = Color.FromArgb(200, 150, 0);
        private static readonly Color MatchRed = Color.FromArgb(200, 50, 50);
        private static readonly Color TagGoldBg = Color.FromArgb(255, 248, 225);
        private static readonly Color TagGoldFg = Color.FromArgb(180, 130, 0);
        private static readonly Color TagNormalBg = Color.FromArgb(245, 245, 245);
        private static readonly Color TagNormalFg = Color.FromArgb(153, 153, 153);

        private static readonly Font TitleFont = new Font("Microsoft YaHei UI", 14, FontStyle.Bold);
        private static readonly Font DescFont = new Font("Microsoft YaHei UI", 11, FontStyle.Regular);
        private static readonly Font MetaFont = new Font("Microsoft YaHei UI", 12, FontStyle.Bold);
        private static readonly Font TagFont = new Font("Microsoft YaHei UI", 10, FontStyle.Regular);
        private static readonly Font SourceFont = new Font("Microsoft YaHei UI", 10, FontStyle.Regular);

        public SlidePreviewForm()
        {
            InitializeForm();
            CreateControls();
        }

        private void InitializeForm()
        {
            this.FormBorderStyle = FormBorderStyle.None;
            this.StartPosition = FormStartPosition.Manual;
            this.ShowInTaskbar = false;
            this.TopMost = true;
            this.BackColor = FormBg;
            this.Size = new Size(PreviewWidth, PreviewThumbHeight + 140);
            this.MinimumSize = this.Size;
            this.MaximumSize = this.Size;

            // 圆角
            int radius = 12;
            var path = new System.Drawing.Drawing2D.GraphicsPath();
            path.AddArc(0, 0, radius, radius, 180, 90);
            path.AddArc(this.Width - radius, 0, radius, radius, 270, 90);
            path.AddArc(this.Width - radius, this.Height - radius, radius, radius, 0, 90);
            path.AddArc(0, this.Height - radius, radius, radius, 90, 90);
            path.CloseFigure();
            this.Region = new Region(path);

            // 点击外部自动关闭
            this.Deactivate += (s, e) => this.Hide();
        }

        private void CreateControls()
        {
            // 缩略图
            _previewThumb = new PictureBox
            {
                Location = new Point(0, 0),
                Size = new Size(PreviewWidth, PreviewThumbHeight),
                SizeMode = PictureBoxSizeMode.Zoom,
                BackColor = Color.FromArgb(245, 245, 245),
                Cursor = Cursors.Default
            };
            this.Controls.Add(_previewThumb);

            // 信息面板
            _infoPanel = new Panel
            {
                Location = new Point(0, PreviewThumbHeight),
                Width = PreviewWidth,
                Height = this.Height - PreviewThumbHeight,
                BackColor = FormBg
            };

            // 标题
            _titleLabel = new Label
            {
                Location = new Point(14, 12),
                Width = PreviewWidth - 28,
                Height = 22,
                Font = TitleFont,
                ForeColor = TextPrimary,
                AutoSize = false,
                TextAlign = ContentAlignment.MiddleLeft
            };
            _infoPanel.Controls.Add(_titleLabel);

            // 描述（4行）
            _descLabel = new Label
            {
                Location = new Point(14, _titleLabel.Bottom + 4),
                Width = PreviewWidth - 28,
                Height = 56,
                Font = DescFont,
                ForeColor = TextSecondary,
                AutoSize = false,
                TextAlign = ContentAlignment.TopLeft
            };
            _infoPanel.Controls.Add(_descLabel);

            // 元信息行
            int metaY = _descLabel.Bottom + 4;
            _matchLabel = new Label
            {
                Location = new Point(14, metaY),
                AutoSize = true,
                Font = MetaFont,
                ForeColor = MatchGreen,
                TextAlign = ContentAlignment.MiddleLeft
            };
            _infoPanel.Controls.Add(_matchLabel);

            _tagLabel = new Label
            {
                Location = new Point(14 + 70, metaY + 2),
                AutoSize = true,
                Font = TagFont,
                ForeColor = TagNormalFg,
                TextAlign = ContentAlignment.MiddleLeft,
                BackColor = TagNormalBg,
                Padding = new Padding(6, 2, 6, 2)
            };
            _infoPanel.Controls.Add(_tagLabel);

            _sourceLabel = new Label
            {
                Location = new Point(PreviewWidth - 14, metaY),
                AutoSize = true,
                Font = SourceFont,
                ForeColor = TextMuted,
                TextAlign = ContentAlignment.MiddleRight
            };
            _sourceLabel.Location = new Point(
                PreviewWidth - 14 - _sourceLabel.PreferredWidth, metaY);
            _infoPanel.Controls.Add(_sourceLabel);

            this.Controls.Add(_infoPanel);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            // 边框
            using (var pen = new Pen(BorderClr, 1))
            {
                var r = new Rectangle(1, 1, this.Width - 2, this.Height - 2);
                e.Graphics.DrawRectangle(pen, r);
                // 右侧小三角指向侧边栏
                int arrowY = 30;
                e.Graphics.DrawLine(pen, this.Width, arrowY, this.Width - 8, arrowY - 6);
                e.Graphics.DrawLine(pen, this.Width, arrowY, this.Width - 8, arrowY + 6);
            }
            // 三角填充
            int arrowY2 = 30;
            using (var brush = new SolidBrush(FormBg))
            {
                Point[] arrow = new Point[]
                {
                    new Point(this.Width, arrowY2),
                    new Point(this.Width - 8, arrowY2 - 6),
                    new Point(this.Width - 8, arrowY2 + 6)
                };
                e.Graphics.FillPolygon(brush, arrow);
            }
            // 阴影（底部和右侧轻微阴影）
            using (var shadowPen = new Pen(Color.FromArgb(20, 0, 0, 0), 3))
            {
                e.Graphics.DrawLine(shadowPen, 2, this.Height, this.Width, this.Height);
                e.Graphics.DrawLine(shadowPen, this.Width, 2, this.Width, this.Height);
            }
        }

        /// <summary>
        /// 更新预览内容
        /// </summary>
        public void UpdatePreview(SlideResult slide, Image thumbnailImage)
        {
            if (slide == null) return;

            if (thumbnailImage != null && _previewThumb != null)
            {
                _previewThumb.Image?.Dispose();
                _previewThumb.Image = thumbnailImage;
            }

            _titleLabel.Text = slide.DeckName ?? "未命名";
            _descLabel.Text = slide.Summary ?? "";

            int matchPct = (int)(slide.Score * 100);
            _matchLabel.Text = $"{matchPct}% 匹配";
            if (matchPct >= 70) _matchLabel.ForeColor = MatchGreen;
            else if (matchPct >= 50) _matchLabel.ForeColor = MatchYellow;
            else _matchLabel.ForeColor = MatchRed;

            bool isGold = slide.LlmScore >= 8;
            _tagLabel.Text = isGold ? "⭐ 金牌" : "推荐";
            _tagLabel.ForeColor = isGold ? TagGoldFg : TagNormalFg;
            _tagLabel.BackColor = isGold ? TagGoldBg : TagNormalBg;
            _tagLabel.Left = _matchLabel.Right + 8;

            string src = slide.DeckName ?? "";
            _sourceLabel.Text = src.Length > 15 ? src.Substring(0, 12) + "…" : src;
            _sourceLabel.Left = PreviewWidth - 14 - _sourceLabel.PreferredWidth;
        }

        /// <summary>
        /// 在指定位置显示浮窗（侧边栏左侧弹出）
        /// </summary>
        public void ShowPreview(Control parent, Point sidebarLocation, int sidebarWidth)
        {
            int x = sidebarLocation.X - PreviewWidth - 4;
            int y = sidebarLocation.Y + 10;
            this.Location = new Point(x, y);
            this.Show();
            this.BringToFront();
        }
    }
}
