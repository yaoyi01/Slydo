using System;
using System.Drawing;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;
using Newtonsoft.Json;
using SlydoAddIn.Services;

namespace SlydoAddIn
{
    public partial class LoginForm : Form
    {
        private readonly TextBox _txtUsername;
        private readonly TextBox _txtPassword;
        private readonly Button _btnLogin;
        private readonly Label _lblError;
        private readonly Label _lblTitle;

        public LoginForm()
        {
            Text = "Slydo 登录";
            Size = new Size(420, 320);
            MinimumSize = new Size(360, 260);
            FormBorderStyle = FormBorderStyle.Sizable;
            MaximizeBox = true;
            MinimizeBox = true;
            StartPosition = FormStartPosition.CenterParent;
            BackColor = Color.White;

            _lblTitle = new Label
            {
                Text = "Slydo 知识库",
                Font = new Font("微软雅黑", 18, FontStyle.Bold),
                ForeColor = Color.FromArgb(26, 26, 46),
                TextAlign = ContentAlignment.MiddleCenter,
                Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right,
                Location = new Point(0, 20),
                Size = new Size(405, 40),
            };

            _txtUsername = new TextBox
            {
                Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right,
                Location = new Point(30, 80),
                Size = new Size(345, 28),
                Font = new Font("微软雅黑", 12),
            };
            // 模拟 PlaceholderText
            _txtUsername.Enter += (s, e) => { if (_txtUsername.Text == "用户名") _txtUsername.Text = ""; };
            _txtUsername.Leave += (s, e) => { if (_txtUsername.Text == "") _txtUsername.Text = "用户名"; };
            _txtUsername.Text = "用户名";

            _txtPassword = new TextBox
            {
                Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right,
                Location = new Point(30, 120),
                Size = new Size(345, 28),
                Font = new Font("微软雅黑", 12),
                UseSystemPasswordChar = true,
            };
            // 模拟 PlaceholderText
            _txtPassword.Enter += (s, e) => { if (_txtPassword.Text == "密码") { _txtPassword.Text = ""; _txtPassword.UseSystemPasswordChar = true; } };
            _txtPassword.Leave += (s, e) => { if (_txtPassword.Text == "") { _txtPassword.Text = "密码"; _txtPassword.UseSystemPasswordChar = false; } };
            _txtPassword.Text = "密码";
            _txtPassword.UseSystemPasswordChar = false;

            _btnLogin = new Button
            {
                Text = "登  录",
                Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right,
                Location = new Point(30, 165),
                Size = new Size(345, 36),
                Font = new Font("微软雅黑", 12, FontStyle.Bold),
                BackColor = Color.FromArgb(24, 144, 255),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat,
                FlatAppearance = { BorderSize = 0 },
                Cursor = Cursors.Hand,
            };
            _btnLogin.FlatAppearance.MouseOverBackColor = Color.FromArgb(64, 169, 255);

            _lblError = new Label
            {
                Text = "",
                ForeColor = Color.Red,
                Font = new Font("微软雅黑", 10),
                TextAlign = ContentAlignment.MiddleCenter,
                Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right,
                Location = new Point(30, 210),
                Size = new Size(345, 30),
            };

            _btnLogin.Click += BtnLogin_Click;
            _txtPassword.KeyDown += (s, e) => { if (e.KeyCode == Keys.Enter) BtnLogin_Click(null, null); };

            Controls.Add(_lblTitle);
            Controls.Add(_txtUsername);
            Controls.Add(_txtPassword);
            Controls.Add(_btnLogin);
            Controls.Add(_lblError);
        }

        private async void BtnLogin_Click(object sender, EventArgs e)
        {
            var username = _txtUsername.Text.Trim();
            var password = _txtPassword.Text;

            if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(password) ||
                username == "用户名" || password == "密码")
            {
                _lblError.Text = "请输入用户名和密码";
                return;
            }

            _btnLogin.Enabled = false;
            _btnLogin.Text = "登录中...";
            _lblError.Text = "";

            try
            {
                using (var client = new HttpClient())
                {
                    client.Timeout = TimeSpan.FromSeconds(10);
                    var baseUrl = ThisAddIn.ApiBaseUrl;
                    var payload = JsonConvert.SerializeObject(new { username, password });
                    var content = new StringContent(payload, Encoding.UTF8, "application/json");

                    var response = await client.PostAsync($"{baseUrl}/api/auth/login", content);
                    var body = await response.Content.ReadAsStringAsync();

                    if (response.IsSuccessStatusCode)
                    {
                        var tokenResp = JsonConvert.DeserializeObject<TokenResponse>(body);
                        TokenManager.SaveFull(tokenResp.access_token, tokenResp.refresh_token, username);
                        DialogResult = DialogResult.OK;
                        Close();
                    }
                    else
                    {
                        try
                        {
                            var err = JsonConvert.DeserializeObject<dynamic>(body);
                            _lblError.Text = err.detail ?? "登录失败";
                        }
                        catch
                        {
                            _lblError.Text = $"登录失败 (HTTP {(int)response.StatusCode})";
                        }
                    }
                }
            }
            catch (HttpRequestException)
            {
                _lblError.Text = "无法连接到 Slydo 服务，请检查网络";
            }
            catch (TaskCanceledException)
            {
                _lblError.Text = "连接超时，请稍后重试";
            }
            catch (Exception ex)
            {
                _lblError.Text = $"错误: {ex.Message}";
            }
            finally
            {
                _btnLogin.Enabled = true;
                _btnLogin.Text = "登  录";
            }
        }
    }
}
