using System;
using System.IO;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using SlydoAddIn.Services;

namespace SlydoAddIn.TaskPane
{
    public partial class SlideCardWpf : UserControl
    {
        public SlideResult SlideData { get; private set; }
        private readonly SlydoApiClient _apiClient;

        public event Action<SlideResult> OnImportRequested;
        public event Action<SlideResult> OnHoverStarted;
        public event Action OnHoverEnded;

        public SlideCardWpf(SlideResult slide, SlydoApiClient client)
        {
            InitializeComponent();
            SlideData = slide;
            _apiClient = client;

            TitleText.Text = slide.DeckName ?? "未命名";
            string summary = slide.Summary ?? "";
            SummaryText.Text = summary.Length > 70 ? summary.Substring(0, 67) + "…" : summary;
            MatchText.Text = $"{(int)(slide.Score * 100)}% 匹配";
            MatchText.Foreground = slide.Score >= 0.7
                ? new SolidColorBrush(Color.FromRgb(0, 153, 0))
                : slide.Score >= 0.5
                    ? new SolidColorBrush(Color.FromRgb(200, 150, 0))
                    : new SolidColorBrush(Color.FromRgb(200, 50, 50));

            if (slide.LlmScore >= 8) GoldBadge.Visibility = Visibility.Visible;

            this.MouseEnter += (s, e) => OnHoverStarted?.Invoke(SlideData);
            this.MouseLeave += (s, e) => OnHoverEnded?.Invoke();

            var importBtn = this.FindName("ImportButton") as TextBlock;
            if (importBtn != null)
            {
                importBtn.MouseLeftButtonUp += (s, e) =>
                {
                    e.Handled = true;
                    OnImportRequested?.Invoke(SlideData);
                };
            }

            LoadThumbnailAsync();
        }

        private async void LoadThumbnailAsync()
        {
            try
            {
                byte[] bytes = await _apiClient.GetThumbnailAsync(SlideData.SlideId);
                if (bytes == null || bytes.Length == 0) return;

                using (var ms = new MemoryStream(bytes))
                {
                    var img = new BitmapImage();
                    img.BeginInit();
                    img.StreamSource = ms;
                    img.CacheOption = BitmapCacheOption.OnLoad;
                    img.EndInit();
                    img.Freeze();

                    Dispatcher.Invoke(() =>
                    {
                        ThumbnailImage.Source = img;
                        ThumbnailImage.Visibility = Visibility.Visible;
                        PlaceholderText.Visibility = Visibility.Collapsed;
                    });
                }
            }
            catch { }
        }

        private ImageSource _previewImage = null;
        public ImageSource GetPreviewImage()
        {
            if (_previewImage != null) return _previewImage;
            return ThumbnailImage.Source;
        }
    }
}
