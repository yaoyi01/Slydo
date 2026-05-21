using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using SlydoAddIn.Services;

namespace SlydoAddIn.TaskPane
{
    public partial class SlideRecommendationWpf : System.Windows.Controls.UserControl
    {
        private readonly SlydoApiClient _apiClient;
        private readonly SlidePreviewWpf _previewForm;
        private List<SlideResult> _currentResults = new List<SlideResult>();
        private bool _isLoading = false;
        // 用于定位预览窗口的 WinForms 父容器引用
        private System.Windows.Forms.UserControl _parentWinFormsControl = null;
        public event Action<SlideResult> OnImportRequested;

        // 设置 WinForms 父容器（用于预览窗口定位）
        public void SetParentWinFormsControl(System.Windows.Forms.UserControl ctrl)
        {
            _parentWinFormsControl = ctrl;
        }

        public SlideRecommendationWpf()
        {
            InitializeComponent();
            _apiClient = new SlydoApiClient();
            _previewForm = new SlidePreviewWpf();

            SearchButton.MouseLeftButtonUp += (s, e) => DoSearch();
            SearchBox.KeyDown += (s, e) =>
            {
                if (e.Key == Key.Enter) DoSearch();
            };

            // ⚙️ 设置按钮：弹出后端地址配置对话框
            SettingsButton.MouseLeftButtonUp += (s, e) => ShowSettingsDialog();
            
            // 🔑 登录按钮：弹出登录窗口
            LoginButton.MouseLeftButtonUp += (s, e) => ShowLoginDialog();
        }

        /// <summary>
        /// 弹出登录窗口
        /// </summary>
        private void ShowLoginDialog()
        {
            try
            {
                var loginForm = new LoginForm();
                if (loginForm.ShowDialog() == System.Windows.Forms.DialogResult.OK)
                {
                    // 登录成功，刷新推荐
                    UpdateConnectionStatus(true);
                    TriggerRecommendation();
                }
            }
            catch (Exception ex)
            {
                System.Windows.MessageBox.Show($"打开登录窗口失败：{ex.Message}",
                    "Slydo", MessageBoxButton.OK, MessageBoxImage.Warning);
            }
        }

        /// <summary>
        /// 更新连接状态和登录按钮显示
        /// </summary>
        public void UpdateConnectionStatus(bool isConnected)
        {
            try
            {
                Dispatcher.Invoke(() =>
                {
                    if (isConnected)
                    {
                        StatusDot.Fill = new SolidColorBrush(Color.FromRgb(0, 153, 0));
                        StatusTextBottom.Text = "已连接";
                        StatusTextBottom.Foreground = new SolidColorBrush(Color.FromRgb(0, 153, 0));
                        LoginButton.Visibility = Visibility.Collapsed;
                    }
                    else
                    {
                        StatusDot.Fill = new SolidColorBrush(Color.FromRgb(200, 60, 60));
                        StatusTextBottom.Text = "未连接";
                        StatusTextBottom.Foreground = new SolidColorBrush(Color.FromRgb(200, 60, 60));
                        LoginButton.Visibility = Visibility.Visible;
                    }
                });
            }
            catch { }
        }

        /// <summary>
        /// 弹出设置对话框，允许用户修改后端 API 地址
        /// </summary>
        private void ShowSettingsDialog()
        {
            try
            {
                var currentUrl = ThisAddIn.ApiBaseUrl;
                var input = Microsoft.VisualBasic.Interaction.InputBox(
                    "请输入 Slydo 后端服务地址：",
                    "Slydo 设置",
                    currentUrl,
                    -1, -1);

                if (!string.IsNullOrWhiteSpace(input) && input != currentUrl)
                {
                    // 持久化到注册表（供下次启动时 ThisAddIn.ApiBaseUrl 读取）
                    Microsoft.Win32.Registry.CurrentUser.CreateSubKey(@"SOFTWARE\Slydo")
                        ?.SetValue("ApiBaseUrl", input.Trim());
                    System.Windows.MessageBox.Show($"后端地址已更新为：\n{input.Trim()}\n\n重启 PowerPoint 后生效。",
                        "Slydo", MessageBoxButton.OK, MessageBoxImage.Information);
                }
            }
            catch (Exception ex)
            {
                System.Windows.MessageBox.Show($"打开设置失败：{ex.Message}",
                    "Slydo", MessageBoxButton.OK, MessageBoxImage.Warning);
            }
        }

        public async void TriggerRecommendation()
        {
            if (_isLoading) return;
            _isLoading = true;
            try
            {
                var response = await _apiClient.GetRecommendationsAsync(topK: 20);
                Dispatcher.Invoke(() => UpdateResults(response));
                await AutoLoadOutlineAsync();
            }
            catch (Exception ex)
            {
                Dispatcher.Invoke(() => SetErrorState(ex.Message));
            }
            finally
            {
                _isLoading = false;
            }
        }

        public async void UpdateCurrentTitle(string title)
        {
            if (string.IsNullOrEmpty(title)) return;
            _isLoading = true;
            try
            {
                var response = await _apiClient.GetRecommendationsAsync(searchText: title, topK: 20);
                Dispatcher.Invoke(() => UpdateResults(response));
                await AutoLoadOutlineAsync();
            }
            catch (Exception ex)
            {
                Dispatcher.Invoke(() => SetErrorState(ex.Message));
            }
            finally
            {
                _isLoading = false;
            }
        }

        /// <summary>
        /// 从 ThisAddIn 调用的大纲入口（空白页时传入已完成标题）
        /// </summary>
        public async void LoadOutline(List<string> completedTitles, string currentTitle)
        {
            try
            {
                var outline = await _apiClient.GetOutlineRecommendationsAsync(
                    completedTitles, currentTitle ?? "", 3);
                Dispatcher.Invoke(() => UpdateOutline(outline));
            }
            catch
            {
                // 大纲加载失败不阻塞
            }
        }

        private void DoSearch()
        {
            var query = SearchBox.Text.Trim();
            if (string.IsNullOrEmpty(query))
                TriggerRecommendation();
            else
                UpdateCurrentTitle(query);

            // 记录搜索行为
            _apiClient.LogSearchAsync(query);
        }

        /// <summary>
        /// 自动加载大纲（推荐/搜索加载完成后调用）
        /// </summary>
        private async Task AutoLoadOutlineAsync()
        {
            try
            {
                var outline = await _apiClient.GetOutlineRecommendationsAsync(
                    new List<string>(), "", 3);
                Dispatcher.Invoke(() => UpdateOutline(outline));
            }
            catch
            {
                // 大纲加载失败不阻塞
            }
        }

        private void UpdateOutline(OutlineResponse response)
        {
            OutlineDirections.Children.Clear();

            // 检查客户端侧错误
            if (!string.IsNullOrEmpty(response?.Error))
            {
                OutlinePanel.Visibility = Visibility.Collapsed;
                StatusText.Text = "⚠️ " + response.Error;
                return;
            }

            if (response?.Directions == null || response.Directions.Count == 0)
            {
                OutlinePanel.Visibility = Visibility.Collapsed;
                return;
            }

            OutlinePanel.Visibility = Visibility.Visible;
            OutlineTitle.Text = $"推荐接下来的 {response.Directions.Count} 个方向";

            foreach (var dir in response.Directions)
            {
                var border = new Border
                {
                    CornerRadius = new CornerRadius(6),
                    Background = Brushes.White,
                    BorderBrush = new SolidColorBrush(Color.FromRgb(224, 224, 224)),
                    BorderThickness = new Thickness(1),
                    Padding = new Thickness(8, 6, 8, 6),
                    Margin = new Thickness(0, 0, 4, 0),
                    Cursor = Cursors.Hand,
                    Tag = dir.Direction ?? ""
                };

                var stack = new StackPanel();
                stack.Children.Add(new TextBlock
                {
                    Text = dir.Direction ?? "",
                    FontSize = 11,
                    FontWeight = FontWeights.SemiBold,
                    Foreground = new SolidColorBrush(Color.FromRgb(51, 51, 51))
                });
                stack.Children.Add(new TextBlock
                {
                    Text = $"{dir.SlideCount} 页",
                    FontSize = 10,
                    Foreground = new SolidColorBrush(Color.FromRgb(170, 170, 170))
                });

                border.Child = stack;
                var dirText = dir.Direction;
                border.MouseLeftButtonUp += (s, e) =>
                {
                    if (!string.IsNullOrEmpty(dirText))
                    {
                        SearchBox.Text = dirText;
                        DoSearch();
                    }
                };
                OutlineDirections.Children.Add(border);
            }
        }

        private void UpdateResults(RecommendResponse response)
        {
            // 检查客户端侧错误（网络异常/超时/服务不可用）
            if (!string.IsNullOrEmpty(response?.RequestError))
            {
                CardList.Items.Clear();
                CardList.Items.Add(new TextBlock
                {
                    Text = $"⚠️ 获取失败\n{response.RequestError}\n\n🔄 点击「搜索」重试",
                    Foreground = new SolidColorBrush(Color.FromRgb(200, 60, 60)),
                    FontSize = 12,
                    TextWrapping = TextWrapping.Wrap,
                    Margin = new Thickness(10, 20, 10, 0)
                });
                StatusText.Text = "⚠️ " + response.RequestError;
                return;
            }

            var results = response.Results ?? new List<SlideResult>();
            _currentResults = results;
            CardList.Items.Clear();

            StatusText.Text = $"找到 {results.Count} 个推荐结果";

            if (results.Count == 0)
            {
                CardList.Items.Add(new TextBlock
                {
                    Text = "暂无推荐结果，试试输入其他关键词搜索",
                    Foreground = new SolidColorBrush(Color.FromRgb(180, 180, 180)),
                    FontSize = 12,
                    TextAlignment = TextAlignment.Center,
                    Margin = new Thickness(0, 20, 0, 0)
                });
                return;
            }

            foreach (var r in results)
            {
                var card = new SlideCardWpf(r, _apiClient);
                card.OnImportRequested += (slide) => OnImportRequested?.Invoke(slide);
                card.OnHoverStarted += (slide) => ShowPreview(slide);
                card.OnHoverEnded += () => HidePreview();
                CardList.Items.Add(card);
            }

            // 离线缓存标识
            if (response._isCached)
                StatusText.Text += " 💾 离线缓存";
        }

        private void SetErrorState(string message)
        {
            CardList.Items.Clear();
            CardList.Items.Add(new TextBlock
            {
                Text = $"❌ 获取失败\n{message}\n\n点击「刷新」重试",
                Foreground = new SolidColorBrush(Color.FromRgb(200, 60, 60)),
                FontSize = 12,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(10, 20, 10, 0)
            });
            StatusText.Text = "❌ 获取失败";
        }

        // ── 悬浮预览 ──
        private void ShowPreview(SlideResult slide)
        {
            if (slide == null) return;

            ImageSource thumb = null;
            foreach (var item in CardList.Items)
            {
                if (item is SlideCardWpf sc && sc.SlideData?.SlideId == slide.SlideId)
                {
                    thumb = sc.GetPreviewImage();
                    break;
                }
            }

            // 使用 WinForms 方式获取屏幕位置（避免 WPF Window.GetWindow 在 ElementHost 中返回 null）
            try
            {
                if (_parentWinFormsControl != null && !_parentWinFormsControl.IsDisposed)
                {
                    // 获取侧边栏控件的屏幕坐标
                    var screenPt = _parentWinFormsControl.PointToScreen(System.Drawing.Point.Empty);
                    _previewForm.UpdatePreview(slide, thumb);
                    _previewForm.ShowPreview(
                        new System.Windows.Point(screenPt.X, screenPt.Y),
                        (int)this.ActualWidth > 0 ? this.ActualWidth : _parentWinFormsControl.Width);
                }
                else
                {
                    // fallback: 用 WPF 方式
                    var win = Window.GetWindow(this);
                    if (win == null) return;
                    var screenPos = win.PointToScreen(new System.Windows.Point(0, 0));
                    _previewForm.UpdatePreview(slide, thumb);
                    _previewForm.ShowPreview(screenPos, this.ActualWidth);
                }
            }
            catch
            {
                // 预览失败不阻塞主流程
            }
        }

        private void HidePreview()
        {
            try
            {
                if (_previewForm != null && _previewForm.IsVisible)
                {
                    _previewForm.Hide();
                }
            }
            catch { }
        }

        public void Cleanup()
        {
            _apiClient?.Dispose();
            if (_previewForm != null)
            {
                _previewForm.Close();
            }
        }
    }
}
