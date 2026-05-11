using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Threading.Tasks;
using Newtonsoft.Json;

namespace SlydoAddIn.Services
{
    /// <summary>
    /// Slydo 后端 API 客户端（含离线缓存）
    /// </summary>
    public class SlydoApiClient : IDisposable
    {
        private readonly HttpClient _httpClient;
        private readonly string _baseUrl;
        private static readonly string CacheDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Slydo", "cache");

        public SlydoApiClient(string baseUrl = null)
        {
            _baseUrl = baseUrl ?? ThisAddIn.ApiBaseUrl;
            _httpClient = new HttpClient();
            _httpClient.BaseAddress = new Uri(_baseUrl);
            _httpClient.Timeout = TimeSpan.FromSeconds(10);
            // 确保缓存目录存在
            try { Directory.CreateDirectory(CacheDir); } catch { }
        }

        /// <summary>
        /// 获取幻灯片推荐（带离线缓存降级）
        /// </summary>
        public async Task<RecommendResponse> GetRecommendationsAsync(string searchText = null, int topK = 20)
        {
            try
            {
                var queryParams = new System.Collections.Generic.List<string>();
                queryParams.Add($"top_k={topK}");
                if (!string.IsNullOrEmpty(searchText))
                    queryParams.Add($"q={Uri.EscapeDataString(searchText)}");
                var query = "?" + string.Join("&", queryParams);
                var response = await _httpClient.GetStringAsync($"/api/v1/recommend/slides{query}");
                var result = Newtonsoft.Json.JsonConvert.DeserializeObject<RecommendResponse>(response);
                // 成功时写缓存
                SaveRecommendCache(searchText ?? "", result);
                return result;
            }
            catch (TaskCanceledException)
            {
                System.Diagnostics.Debug.WriteLine("[Slydo] 推荐请求超时");
                return TryLoadRecommendCache(searchText ?? "", "请求超时，已显示缓存数据");
            }
            catch (HttpRequestException ex)
            {
                System.Diagnostics.Debug.WriteLine($"[Slydo] 推荐请求失败: {ex.Message}");
                return TryLoadRecommendCache(searchText ?? "", "服务不可用，已显示缓存数据");
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"[Slydo] 推荐异常: {ex.Message}");
                return TryLoadRecommendCache(searchText ?? "", "网络异常，已显示缓存数据");
            }
        }

        // ── 推荐缓存 ──

        private string GetRecommendCachePath(string key)
        {
            string safeName = string.IsNullOrEmpty(key) ? "_default" : key.GetHashCode().ToString("x");
            return Path.Combine(CacheDir, $"recommend_{safeName}.json");
        }

        private void SaveRecommendCache(string key, RecommendResponse data)
        {
            try
            {
                var cache = new RecommendCache { Data = data, CachedAt = DateTime.Now };
                File.WriteAllText(GetRecommendCachePath(key),
                    Newtonsoft.Json.JsonConvert.SerializeObject(cache));
            }
            catch { }
        }

        private RecommendResponse TryLoadRecommendCache(string key, string fallbackMessage)
        {
            try
            {
                var path = GetRecommendCachePath(key);
                if (File.Exists(path))
                {
                    var cache = Newtonsoft.Json.JsonConvert.DeserializeObject<RecommendCache>(
                        File.ReadAllText(path));
                    if (cache?.Data != null)
                    {
                        cache.Data.RequestError = fallbackMessage;
                        cache.Data._isCached = true;
                        return cache.Data;
                    }
                }
            }
            catch { }
            return new RecommendResponse { RequestError = "暂无缓存数据，请稍后重试" };
        }

        /// <summary>
        /// 导出幻灯片到本地文件
        /// </summary>
        public async Task<string> ExportSlideAsync(string slideId, int targetIndex)
        {
            var url = $"/api/v1/recommend/export?slide_id={Uri.EscapeDataString(slideId)}&target_index={targetIndex}";
            var response = await _httpClient.GetAsync(url);
            response.EnsureSuccessStatusCode();

            var tempPath = Path.Combine(Path.GetTempPath(), $"slydo_export_{Guid.NewGuid():N}.pptx");
            using (var fs = new FileStream(tempPath, FileMode.Create, FileAccess.Write))
            {
                await response.Content.CopyToAsync(fs);
            }
            return tempPath;
        }

        /// <summary>
        /// 获取幻灯片缩略图
        /// </summary>
        public async Task<byte[]> GetThumbnailAsync(string slideId)
        {
            var response = await _httpClient.GetAsync($"/api/v1/thumbnails/{Uri.EscapeDataString(slideId)}");
            response.EnsureSuccessStatusCode();
            return await response.Content.ReadAsByteArrayAsync();
        }

        /// <summary>
        /// 场景 B：获取大纲推荐（带离线缓存降级）
        /// </summary>
        public async Task<OutlineResponse> GetOutlineRecommendationsAsync(List<string> completedTitles, string currentTitle = "", int topK = 3)
        {
            try
            {
                var titlesStr = string.Join(",", completedTitles);
                var url = $"/api/recommend/outline?titles={Uri.EscapeDataString(titlesStr)}&current={Uri.EscapeDataString(currentTitle)}&top_k={topK}";
                var response = await _httpClient.GetStringAsync(url);
                var result = Newtonsoft.Json.JsonConvert.DeserializeObject<OutlineResponse>(response);
                SaveOutlineCache(completedTitles, currentTitle, result);
                return result;
            }
            catch (TaskCanceledException)
            {
                System.Diagnostics.Debug.WriteLine("[Slydo] 大纲请求超时");
                return TryLoadOutlineCache(completedTitles, currentTitle, "请求超时");
            }
            catch (HttpRequestException ex)
            {
                System.Diagnostics.Debug.WriteLine($"[Slydo] 大纲请求失败: {ex.Message}");
                return TryLoadOutlineCache(completedTitles, currentTitle, "服务不可用");
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"[Slydo] 大纲异常: {ex.Message}");
                return TryLoadOutlineCache(completedTitles, currentTitle, "网络异常");
            }
        }

        // ── 大纲缓存 ──

        private string GetOutlineCacheKey(List<string> titles, string current)
        {
            string joined = string.Join(",", titles ?? new List<string>()) + "|" + (current ?? "");
            return joined.GetHashCode().ToString("x");
        }

        private void SaveOutlineCache(List<string> titles, string current, OutlineResponse data)
        {
            try
            {
                var cache = new OutlineCache { Data = data, CachedAt = DateTime.Now };
                File.WriteAllText(Path.Combine(CacheDir, $"outline_{GetOutlineCacheKey(titles, current)}.json"),
                    Newtonsoft.Json.JsonConvert.SerializeObject(cache));
            }
            catch { }
        }

        private OutlineResponse TryLoadOutlineCache(List<string> titles, string current, string fallbackMessage)
        {
            try
            {
                var path = Path.Combine(CacheDir, $"outline_{GetOutlineCacheKey(titles, current)}.json");
                if (File.Exists(path))
                {
                    var cache = Newtonsoft.Json.JsonConvert.DeserializeObject<OutlineCache>(
                        File.ReadAllText(path));
                    if (cache?.Data != null)
                    {
                        cache.Data._isCached = true;
                        cache.Data.Error = fallbackMessage;
                        return cache.Data;
                    }
                }
            }
            catch { }
            return new OutlineResponse { Error = "暂无缓存" };
        }

        public void Dispose()
        {
            _httpClient?.Dispose();
        }

        /// <summary>
        /// 获取 API 基础地址（用于构造缩略图 URL 等）
        /// </summary>
        public string GetBaseUrl()
        {
            return _baseUrl;
        }
    }
}
