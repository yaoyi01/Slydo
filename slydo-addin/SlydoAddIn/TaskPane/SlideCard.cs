using System;
using System.Drawing;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;
using SlydoAddIn.Services;

namespace SlydoAddIn.TaskPane
{
    /// <summary>
    /// 单页推荐卡片：水平布局（缩略图左 + 文字右）+ 悬浮预览浮窗
    /// 亮色/白色主题
    /// </summary>
    public class SlideCard : UserControl
    {
        public SlideResult SlideData { get; private set; }
        private readonly SlydoApiClient _apiClient;

        // 控件
        private Panel _mainBody;
        private PictureBox _thumbnailBox;
        private PictureBox _starBox;       // 金牌标记图标
        private Label _titleLabel;
        private Label _summaryLabel;
        private Label _scoreLabel;
        private Label _sourceLabel;
        private Button _importBtn;

        // 缓存缩略图
        private byte[] _thumbnailBytes;

        // 事件：点击卡片触发导入
        public event Action<SlideResult> OnImportRequested;
        // 事件：悬浮时请求预览
        public event Action<SlideResult, Rectangle> OnHoverPreviewRequested;
        public event Action OnHoverPreviewEnd;

        // ── 亮色主题颜色 ──
        private static readonly Font CardTitleFont = new Font("Microsoft YaHei UI", 12, FontStyle.Bold);
        private static readonly Font CardSummaryFont = new Font("Microsoft YaHei UI", 10.5f, FontStyle.Regular);
        private static readonly Font CardMetaFont = new Font("Microsoft YaHei UI", 11, FontStyle.Bold);
        private static readonly Font CardSourceFont = new Font("Microsoft YaHei UI", 9, FontStyle.Regular);
        private static readonly Font ImportBtnFont = new Font("Microsoft YaHei UI", 10, FontStyle.Regular);

        private static readonly Color CardBack = Color.White;
        private static readonly Color CardHover = Color.FromArgb(240, 244, 255);    // #f0f4ff 浅蓝悬停
        private static readonly Color BorderClr = Color.FromArgb(220, 222, 228);      // #dcdee4
        private static readonly Color AccentClr = Color.FromArgb(108, 99, 255);       // #6c63ff
        private static readonly Color AccentLightClr = Color.FromArgb(108, 99, 255);  // 保持一致
        private static readonly Color TextPrimary = Color.FromArgb(51, 51, 51);       // #333
        private static readonly Color TextSecondary = Color.FromArgb(102, 102, 102);  // #666
        private static readonly Color TextMuted = Color.FromArgb(170, 170, 170);      // #aaa
        private static readonly Color MatchGreen = Color.FromArgb(0, 150, 0);         // 更稳重的绿色
        private static readonly Color TitleClr = Color.FromArgb(33, 33, 33);          // #212121

        // ── 嵌入的星星图标 PNG（同原版） ──
        private static readonly byte[] StarGoldBytes = Convert.FromBase64String(
            "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAABmJLR0QA/wD/AP+gvaeTAAAFl0lEQVR4nO2bW4gcRRSGv1M72d2antmoyezsKkFERNGgMVmjQQyigoL64kNAHyKoIBExIkYF7w/CIgpGjAjqgySI0QejUfGCmEAMmGxUvEREvCy5be8kwWSmu/faxweTsCY76zpT3W0u/9Nud9Wp//xUnTpddUY4hHDAXq7CCoXFQIkTExWBDRh51iuFfQACEPj5uxVdBbRkSi89jInKMq8rfE3CPXZhbNjMyeP8YYyJkUVGDQ9x8jkPkNNxXSE13w5y4q75f4NvgNlZs8gQJcOhQHiSQkymwyt9KH1ZUpCabzW74ePrIScQf5wRAc1lNDACm7zy8KcwTG3QbkC5OgsemS2B2OhjR/6Gx7PikZEA+nGxNLTx8H8dndEm0E+yYJKFAGpiefLoh2LMo0Dq8Sh1AQTezXdHW45+7pXCbQrr0uaTtgCxYp6u/7blcSBOj076ArxZKAff1XtZ7K79CLyZIp9E84BRkF9At6Fsiw3bipVoi1zEyFSdVGmpDRQuEDO2AJUFIixQmA/YBDiqKwHGgB9UtM+o6cOwNT87/F6EUQe2UWVGuDd/MTE9scQ9otIDzAWazWOcCTAK5uZCOUhlKwsq+Rs11nU4EMBVDJgB8TvBYP5SR/bqItxjF2qsa2neecBtECyq6ofR7vazHdr8Bw4Mtp0XG9YDniubrneB7vEW89Gff8483bFdgkr+zBY1nwGdLu0msA3qhbnhkXX6O+2uLO7ff/pMjfUjwPnsSioPWBxY+4Zq8/Z1B7Z1dGg9cIkDXscguURIWBIM2t5mTKjSErbaNcBVjlgdg6QzwRXVgfZrGu0c+PZehVtcEjoaiafCamTKzG8qiMiQSy6TIXEBWlV3N9pXRfpdcpkMSQugbeFQwwLEZvQPh1wmRdIC7JdzaHgaF6ORfhI+JElagF3NdJY5REDFEZdJkfCpsNYVoFKhaNXeAxBJ9HKpRLVO0z9wnP1NRKIzQOXYGVCpUKwN2OU2tr+g9KL02tj+XvXzT02WQgskGgiTXQJqjgiwbx8dtUH7sI1tP8ILQHlCy1mCPpkbHumv+bb3wI6OM46Y+HsGJIZEBTDKroO7i7Orfv6ptjHbj9ILTPWhVAQezrWO9tcG7Mqgku9OeitM9mpM+AJlIY1/vgYIWxO8NXJ2InS8wtmJ0HGLUwJkTSBrnBIgawJZ45QAWRPIGpmVyChsFpWNIvFwjFwqcAPQljaPLATYCfEdxfLwZxMfhnvtWfG4PAO6lBRL91LNBBXejUdm3DVzzsH99doEA/mbVPR1EvwEnkgpLQEiQR7wyuEr02kcVPLdGusaoOET5WkihVRY5CcwV0zXeQCvFO7xOqPrUO4HN1fs9ZC0AKu9sbBnqqqQehBBC13RSqNcRYJnAkkJcECVWwvlaKmcSdiMoXxX9FU8nrsM4QNX5CYiiRjwVQ69rb089JtLo6pI4Nv7EJ4FWl2ZdSlAjPKSV44edFUaMxmCSr6HWN9SONeBOWdBcKcavabQFS1P0nkArxT2DeWi+QhvubDX/PU1vBeP5uZNLH1NGrNmcbDQGd0Kejs0F2OaWQJDKI945ehFkfRLXA+juqf1QjFmLcjcBro3ugRkO5jLC13RyiydByh2j2wPZWgRsLqR/o3MgNWeRsuki6CRAZNEzW9fKsgqhcI0u/ynXWCvqNzpdYXvN0owDRystJ1vYrOW6ZXUTHsJfG5amPd/dx6gozT8sxdGV6C8OJ32UvNtBHUrukaAR73O6Pms13ojqA7aJaLyKmhHnSaRUfi2zsufxciiQjl67nh0HqDYGb09xvj8er9MU/jGCPETHFWEoOirnkYLvFL4dSpME8Rp5eFfvX3RlYcuZCf6qaL6BAA1v/26qm8313y7q+rbRKuyskQwkL+55tudVd9+WRtovxbgL1OHHWY8...");
        private static readonly byte[] StarSilverBytes = Convert.FromBase64String(
            "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAABmJLR0QA/wD/AP+gvaeTAAAFrElEQVR4nO2bW2gcVRjH/9/ZXWIsaRQTpfrQJxGKqE1Ces1mztl9CNj60Ic+VmlFrVRaCvFC7UVBKEXBltoK9YK0FBvBVouhJp2ZbBsC2kTFS6VIpYGqD1sr1ki6Ozvn8yFZSJNMSXbPzKjpD/ZhZ8758j//zLnMOd8SxnEcZwkRdQJIA2jE/5M8gD4Ae6SUgwBAAOC67tMA3gKQiE1atJQAbJRSvkO2bbcKIQYwdxpfpgRgmRBCPI+513gASBJRp8BYn5+TMHO7ANAQt5C4YOZGgfGBcC5CRCRi1jA4/omNZJx/XGu9jcY4FZeGOA3oz2QyPQDgum4fACsOEbF1AWZ+ecLX7XHpiMuAU0qpXPmLlLIfwOdxCInDANZa75xykXkbAI5aTOQGENHxTCbz5eTrSqkhACei1hOpAcysS6XSKze5v52ZdZSaIjWAiI5ms9lvg+4rpX4goqNRagpzGvSI6Cet9RARDQEYyufzUx79yeTz+ScaGhp2A2gWQjQzczOAJgC1YYgk13VNDDwlAN9jfGWntT5XX1//XUtLi2cgNgYHB1PXrl17iIhaAJQ/D6L6fyCbMsBj5tVKqUimMsdxHiWiEzBggKkxIEVEH+VyucWG4gVi23YrER2Doe5rchCs01p/Ztv2QoMxbyCXy92fSCROAphnKqbpWWBBIpHoPnv27J2G46Knp+derXUvM99tMq7xaZCZF/m+f8J13dtMxezt7a1PpVLdAIw/XaGsA5g5TUQf7Nq1q+r4AwMDtclk8iSAhw1Im0JoCyFmXptOp3dXE6OrqytRLBaPAGgzJGsKoa4EiajTtm1Vaf3GxsZNzLzGpKbJhL4UFkIUq6h+3ZiQAEI3wPf9X6uoPmxMSABhG8CJRKIaAy6ZEhJE2AZclVJW/BjX1NQMI+RNkrAHwV+qqb98+fJRIsqb0jMdoe4KM3OgAf39/XWe5z0LAKlU6sDKlSv/Cih6CYDR1d9Ewt4Wn2LAeMPXe573EoB7AMDzvE7Xdfcnk8m9bW1tf0wsz8zDAFrDEhiZAd3d3fNra2s3ep73AoDJ7wp3AdhZKpW2uq57oFAo7Ono6LgKAMx8iSi80ztT+wHTByd6ipmPA9gEYDOAO2ZYdYSI3hNC7PZ9fw2A/SFJNLYhEoSLsce30tfXvwGcQ3inRhx2F5BV1p+HkI/M4j4djp1bBsQtIG5uGRC3gLi5ZUDcAuImthQZIhrQWueIqABgMYAOADVR64jDgMtEtN6yrN6JF23bvk8I8RqAdYgwdS/spfBkjhcKhSfLLzrT4bruKiJ61/QBSAChvwuUGQWwVUr59kwKnzlzZoHW+ggzV7yjPEOMHY7ejB99318608YDQDqd/q29vT0LYAsAI0fsQYRqADMfHhkZablZVkgQRMRSyr3M3IYQN0fD6gJ/AnhGSvmhiWCu6zYAeB/AKhPxJhBKF/jC9/0mU40HACnlFcuyHgOwhYiqOWiZgjEDmFkT0b66urq2bDb7s6m4ZSZ0iRUALpqKa8qAywCUZVmbTeUFBSGlHBwdHW0CYOQJMzEGfOL7/oZsNvu7CUGzwXGcdUKIg8x8e4UhqloHXAfwomVZ+4go8hTXMqdPn16USCSOYSxrbLZUNggS0Xnf95dIKffG2XgAyGaz5wEsY+bDldSftQHMfLhQKLRWMreHhZRyRCm1jpkfBzAym7qz6QJXmHmDUurT2UuMDsdxHhhPo5tJSs2Mu4CttX7k3954AFBKXQCwlIj2zaQ8ua47CmDajC4iKjLzNsuy3oi7r1eC4zhrhRCHmHl+QJFRAeCbgJsXfN9fJqV8/b/YeABQSnX5vt+EgF+mEdHXgoh2YFISAjMfKhaLzZlM5qsohIZJJpO5mM/nVwB4Eze2k7XWO8q/Hs8CeJWIFmqtn1NKfRyH2LD...");
        private static readonly byte[] StarGrayBytes = Convert.FromBase64String(
            "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAABmJLR0QA/wD/AP+gvaeTAAAIGElEQVR4nO1bbYxUVxl+3nuAYakUptAggkpSiBaxQXe2KKDk7j13ZztU+2E7pljwowE0aYHGNKnU2C3W+ENtKBZL8YcGWxOWEK2rG2bP3XsjM6WxjiXUCMRiUhVtU3W3aDs7uzvnvv7YGbg77ge7c+9MUZ9fk/c9553nPDPnnPee815CAI7jLAKwE8DNAK4DMAf/HSgBeA3ALwHsl1I+X3FQ5YNS6nYi+iGAuXWnV2cw8xP9/f270um0ngEASqkkEXUCEA3mVhcQ0b3xeLwE4H7yPO8dWutzABYF2ngAjgF4oyEMw8dMAKsBbAEwq2xjZm6e4fv+3QgMnog6LMt6pAEkI4dS6ntElAVwFQAionsMZm4LtDmTzWa/3iB+kcO27ZNE9K2AqdkAsDRgONHR0eHXmVe9kQ18bjIAxAKGC3UmU3cQUXCMZDSMCQCl1Lze3t5UIzk0VAAi+rLv+3s9z5vRKA4NE8DzvIUYyTpXlEqlLY3i0TABtNYPArgaAIjo4e7u7tgkXSJBQwQ4duzYYgBfCpjeE4vFtjaCS0MEEEJ8DVUPWsz8UFdXV90fvuougOd5y4joC2O43tnU1HRvvfnUXQCt9SO4lI9X48FsNhuvJ5+6CtDb2/s+AJsmaBIfHBzcVS8+ABDp/uu67hLf9xOGYSSYOeH7/prL+M7djuPcRER53/fzRJQXQpw2TbMUBcfQBPA8b36pVFpFRM0A1gFYz8yLiQjMPFVOLczcQjRyXqO1HnYc52UAOWZ+Tgjxm+PHj58J47klFAGYmRzHeYyIPh9GvDEwE8BKACuJaJvv++c3bNjwUQDnaw0cyhpARByPx7cDyIQRbxJcYOaUaZo1Dx4IcRFMJBLDs2fPvhPAybBijoEh3/c/Zdv2b8MKGOousH79+n+VSqWNAP4YZtwyGMA9bW1tbphBQ98G29vbX2XmmwD0hRz6ASnl0yHHjCYPsG37DIBbARTDiMfMB6SU3wkjVjUiS4SklFlm/iyAWreqrv7+/shS5EgzQdu2OwEcqCHEq3PmzPl0Op3WYXGqRuSpMDPX8g+IrV27diA0MmMgcgGIaEkN3a85ceJEU2hkxkA9HoZqEQADAwPvCovIWHjbCxBC/wkRqQCdnZ0Co+8cp4MrV4D58+cvwvgPXG8C+CaAzUR0doIwV64AhmGMRb4AYJ8QYoWUcreU8ulsNvsBIkoD+H11Y9/3r1wBMPrXGwJw0Pf9FVLKnaZpvlZxdHR0+JZlHcnlctcTUZqZz1V8Ne4ikyLqG5klAIYB/ICI9liW9ZeJGpcPOI7k8/mf9vf330VEDyPiKRC1AC8x83Lbtv80lU6JRGIYwKHu7u7DsVjskxFxAxCxAFLK7OStxkcqlRoEcCQkOmOioZejbwf8X4BGE2g0/ucFaEhhQiaTWSWE2MrMzYZhzGPmPzDzL4aHhw+nUql/1pFKfUtklFLzHMd5SgjxEoAdRLSOmVcBuIWIDsZisXOu636RmWmyWGGhbgIopT4IIA9gGwIlukEw87XM/KTruo7neUvHahM26iKA67qfI6LniWh5wPwyEd3PzNsAOFVdWrXWJ5VSG6PmFukakMvl5haLxSeZ+TNVroNDQ0M7yokOAHzfdd1PMPN+AO8u2xYSUZfjON/t6+t7IJ1OD0VAkSP7BziO01IsFk8CCA7+AhGlpZTbA4MHAFiW1SWEuAHA0YCZAOyIx+PHPc9bFgHN8BfB8kXpTgA5jLxzUEFeCJGwLGvc1NY0zTeklHeUj9MLF1kSrdFan1JKpcOmG6oA3d3d1zqO83MAexGoygawr6+vb51pmufG730Jtm0fAtAC4HcB89VEdFgpdSjMg9LQBOjp6bFmzZp1ioguVn4S0d8Mw7hZSrlzqnNYSnlaCPERAKOuw4hoc6FQyHmet3ycrlN...");

        public SlideCard(SlideResult slide, SlydoApiClient client)
        {
            SlideData = slide;
            _apiClient = client;

            this.AutoSize = true;
            this.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            this.Size = new Size(200, 100);
            this.MinimumSize = new Size(80, 100);
            this.Margin = new Padding(0, 0, 0, 6);
            this.BackColor = CardBack;
            this.BorderStyle = BorderStyle.None;
            this.Cursor = Cursors.Hand;

            CreateChildControls();
            BindEvents();
            LoadThumbnailAsync();
        }

        private void CreateChildControls()
        {
            _mainBody = new Panel
            {
                Dock = DockStyle.Fill,
                Height = 94,
                BackColor = Color.Transparent
            };

            // 缩略图 130×74 (16:9)
            _thumbnailBox = new PictureBox
            {
                Location = new Point(10, 10),
                Size = new Size(130, 74),
                SizeMode = PictureBoxSizeMode.Zoom,
                BackColor = Color.FromArgb(245, 245, 245),
                Cursor = Cursors.Hand,
                Image = CreatePlaceholderImage()
            };
            _mainBody.Controls.Add(_thumbnailBox);

            // 金牌标记
            byte[] starBytes;
            if (SlideData != null)
            {
                if (SlideData.LlmScore >= 8) starBytes = StarGoldBytes;
                else if (SlideData.LlmScore >= 5) starBytes = StarSilverBytes;
                else starBytes = StarGrayBytes;
            }
            else starBytes = StarGrayBytes;

            Image starImg;
            using (var ms = new MemoryStream(starBytes))
            {
                starImg = Image.FromStream(ms);
            }

            _starBox = new PictureBox
            {
                Size = new Size(20, 20),
                SizeMode = PictureBoxSizeMode.Zoom,
                BackColor = Color.Transparent,
                Image = starImg,
                Cursor = Cursors.Hand,
                Enabled = false,
                Location = new Point(_thumbnailBox.Right - 24, _thumbnailBox.Top + 4)
            };
            _mainBody.Controls.Add(_starBox);
            _starBox.BringToFront();

            // ── 文字区域 ──
            int textX = _thumbnailBox.Right + 10;
            int textW = 340 - textX - 10;

            // 标题（1行）
            _titleLabel = new Label
            {
                Location = new Point(textX, 12),
                Size = new Size(textW, 18),
                Font = CardTitleFont,
                ForeColor = TitleClr,
                TextAlign = ContentAlignment.MiddleLeft,
                AutoSize = false
            };
            var titleText = SlideData.DeckName ?? "未命名";
            if (titleText.Length > 45) titleText = titleText.Substring(0, 42) + "…";
            _titleLabel.Text = titleText;
            _mainBody.Controls.Add(_titleLabel);

            // 摘要（2行）
            _summaryLabel = new Label
            {
                Location = new Point(textX, _titleLabel.Bottom + 3),
                Size = new Size(textW, 30),
                Font = CardSummaryFont,
                ForeColor = TextSecondary,
                TextAlign = ContentAlignment.TopLeft,
                AutoSize = false
            };
            var summary = SlideData.Summary ?? "";
            if (summary.Length > 75) summary = summary.Substring(0, 72) + "…";
            _summaryLabel.Text = summary;
            _mainBody.Controls.Add(_summaryLabel);

            // 匹配度 + 来源
            int metaY = _summaryLabel.Bottom + 2;
            _scoreLabel = new Label
            {
                Location = new Point(textX, metaY),
                AutoSize = true,
                Font = CardMetaFont,
                ForeColor = MatchGreen,
                TextAlign = ContentAlignment.MiddleLeft,
                Text = $"{(int)(SlideData.Score * 100)}% 匹配"
            };
            _mainBody.Controls.Add(_scoreLabel);

            _sourceLabel = new Label
            {
                Location = new Point(textX + 70, metaY + 1),
                AutoSize = true,
                Font = CardSourceFont,
                ForeColor = TextMuted,
                TextAlign = ContentAlignment.MiddleLeft
            };
            _mainBody.Controls.Add(_sourceLabel);

            this.Controls.Add(_mainBody);

            // 导入按钮（全宽）
            _importBtn = new Button
            {
                Text = "+ 导入到当前 PPT",
                Font = ImportBtnFont,
                FlatStyle = FlatStyle.Flat,
                BackColor = Color.Transparent,
                ForeColor = AccentClr,
                FlatAppearance = { BorderColor = AccentClr, BorderSize = 1 },
                Cursor = Cursors.Hand,
                Height = 28,
                Dock = DockStyle.Bottom,
                TextAlign = ContentAlignment.MiddleCenter
            };
            _importBtn.Click += (s, e) =>
            {
                OnImportRequested?.Invoke(SlideData);
            };
            _importBtn.MouseEnter += (s, e) =>
            {
                _importBtn.BackColor = AccentClr;
                _importBtn.ForeColor = Color.White;
            };
            _importBtn.MouseLeave += (s, e) =>
            {
                _importBtn.BackColor = Color.Transparent;
                _importBtn.ForeColor = AccentClr;
            };
            this.Controls.Add(_importBtn);

            // Resize
            this.Resize += (s, e) =>
            {
                int bw = this.Width - 20;
                int textWidth = bw - 140;
                if (textWidth < 50) textWidth = 50;
                _titleLabel.Width = textWidth;
                _summaryLabel.Width = textWidth;
            };
        }

        private void BindEvents()
        {
            MouseClick += (s, e) => OnImportRequested?.Invoke(SlideData);
            _thumbnailBox.MouseClick += (s, e) => OnImportRequested?.Invoke(SlideData);
            _titleLabel.MouseClick += (s, e) => OnImportRequested?.Invoke(SlideData);
            _summaryLabel.MouseClick += (s, e) => OnImportRequested?.Invoke(SlideData);
            _scoreLabel.MouseClick += (s, e) => OnImportRequested?.Invoke(SlideData);

            // 悬浮高亮 + 预览
            MouseEnter += (s, e) =>
            {
                this.BackColor = CardHover;
                OnHoverPreviewRequested?.Invoke(SlideData, this.RectangleToScreen(this.ClientRectangle));
            };
            MouseLeave += (s, e) =>
            {
                this.BackColor = CardBack;
                OnHoverPreviewEnd?.Invoke();
            };

            foreach (Control c in _mainBody.Controls)
            {
                c.MouseEnter += (s, e) =>
                {
                    this.BackColor = CardHover;
                    OnHoverPreviewRequested?.Invoke(SlideData, this.RectangleToScreen(this.ClientRectangle));
                };
                c.MouseLeave += (s, e) =>
                {
                    this.BackColor = CardBack;
                    OnHoverPreviewEnd?.Invoke();
                };
            }
        }

        private async void LoadThumbnailAsync()
        {
            try
            {
                _thumbnailBytes = await _apiClient.GetThumbnailAsync(SlideData.SlideId);
                using (var ms = new MemoryStream(_thumbnailBytes))
                {
                    var img = Image.FromStream(ms);
                    if (_thumbnailBox != null && !_thumbnailBox.IsDisposed)
                    {
                        if (_thumbnailBox.InvokeRequired)
                        {
                            _thumbnailBox.BeginInvoke(new Action(() =>
                            {
                                _thumbnailBox.Image?.Dispose();
                                _thumbnailBox.Image = img;
                            }));
                        }
                        else
                        {
                            _thumbnailBox.Image?.Dispose();
                            _thumbnailBox.Image = img;
                        }
                    }
                }
            }
            catch { }
        }

        // ── 悬浮预览用 ──
        private Image _previewImage = null;
        public Image GetPreviewImage()
        {
            if (_previewImage != null) return _previewImage;
            try
            {
                if (_thumbnailBytes == null) return _thumbnailBox?.Image;
                using (var ms = new MemoryStream(_thumbnailBytes))
                {
                    _previewImage = Image.FromStream(ms);
                }
                return _previewImage;
            }
            catch { return _thumbnailBox?.Image; }
        }

        public string GetFullTitle() => SlideData?.DeckName ?? "未命名";
        public string GetFullSummary() => SlideData?.Summary ?? "";
        public int GetMatchPercent() => (int)((SlideData?.Score ?? 0) * 100);
        public bool IsGold() => SlideData?.LlmScore >= 8;

        private static Image CreatePlaceholderImage()
        {
            var bmp = new Bitmap(260, 148);
            using (var g = Graphics.FromImage(bmp))
            using (var bg = new SolidBrush(Color.FromArgb(245, 245, 245)))
            using (var fg = new SolidBrush(Color.FromArgb(180, 180, 180)))
            using (var font = new Font("Microsoft YaHei UI", 10))
            {
                g.FillRectangle(bg, 0, 0, 260, 148);
                g.DrawString("加载中…", font, fg, 90, 64);
            }
            return bmp;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            using (var pen = new Pen(BorderClr, 1))
            {
                var r = new Rectangle(0, 0, this.Width - 1, this.Height - 1);
                e.Graphics.DrawRectangle(pen, r);
            }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _thumbnailBox?.Image?.Dispose();
                _previewImage?.Dispose();
                _starBox?.Image?.Dispose();
            }
            base.Dispose(disposing);
        }
    }
}
