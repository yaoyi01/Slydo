using System;
using System.IO;
using System.Text;

namespace SlydoAddIn.Services
{
    /// <summary>
    /// Token 持久化管理（本地加密存储）
    /// </summary>
    public static class TokenManager
    {
        private static readonly string TokenDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Slydo");
        private static readonly string TokenFile = Path.Combine(TokenDir, ".token");

        private static string _accessToken;
        private static string _refreshToken;
        private static string _username;

        public static string AccessToken => _accessToken;
        public static string RefreshToken => _refreshToken;
        public static string Username => _username;

        static TokenManager()
        {
            try { Directory.CreateDirectory(TokenDir); } catch { }
            Load();
        }

        /// <summary>保存 Token 到内存 + 磁盘</summary>
        public static void Save(string accessToken, string refreshToken)
        {
            _accessToken = accessToken;
            _refreshToken = refreshToken;
            try
            {
                // 简单混淆存储（非生产级加密）
                var data = Convert.ToBase64String(Encoding.UTF8.GetBytes(
                    $"{accessToken}|||{refreshToken}"));
                File.WriteAllText(TokenFile, data);
            }
            catch { }
        }

        /// <summary>保存 Token 和用户名</summary>
        public static void SaveFull(string accessToken, string refreshToken, string username)
        {
            _username = username;
            Save(accessToken, refreshToken);
        }

        /// <summary>从磁盘加载 Token</summary>
        private static void Load()
        {
            try
            {
                if (!File.Exists(TokenFile)) return;
                var raw = File.ReadAllText(TokenFile);
                var decoded = Encoding.UTF8.GetString(Convert.FromBase64String(raw));
                var parts = decoded.Split(new[] { "|||" }, StringSplitOptions.None);
                if (parts.Length == 2)
                {
                    _accessToken = parts[0];
                    _refreshToken = parts[1];
                }
            }
            catch
            {
                Clear();
            }
        }

        /// <summary>清除 Token（登出）</summary>
        public static void Clear()
        {
            _accessToken = null;
            _refreshToken = null;
            try { if (File.Exists(TokenFile)) File.Delete(TokenFile); } catch { }
        }

        /// <summary>是否已登录</summary>
        public static bool IsLoggedIn => !string.IsNullOrEmpty(_accessToken);
    }

    /// <summary>
    /// 登录响应模型
    /// </summary>
    public class TokenResponse
    {
        public string access_token { get; set; }
        public string refresh_token { get; set; }
        public string token_type { get; set; }
        public int expires_in { get; set; }
    }

    /// <summary>
    /// 登录请求模型
    /// </summary>
    public class LoginRequest
    {
        public string username { get; set; }
        public string password { get; set; }
    }

    /// <summary>
    /// 刷新请求模型
    /// </summary>
    public class RefreshRequest
    {
        public string refresh_token { get; set; }
    }

    /// <summary>
    /// 登录结果
    /// </summary>
    public class LoginResult
    {
        public bool Success { get; set; }
        public string Error { get; set; }
    }
}
