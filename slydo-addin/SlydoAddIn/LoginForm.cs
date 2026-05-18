using System;
using System.Drawing;
using System.Net.Http;
using System.Text;
using System.Windows.Forms;
using Newtonsoft.Json;

namespace SlydoAddIn
{
    public partial class LoginForm : Form
    {
        private readonly TextBox _txtUsername;
        private readonly TextBox _txtPassword;
        private readonly Button _btnLogin;
        private readonly Label _lblError;
        private readonly Label _lblTitle;
        private readonly PictureBox _logo;

        public LoginForm()
        {
            Text = "Slydo 登录";
            Size = new Size(360, 300);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            StartPosition = FormStartPosition.CenterParent;
            BackColor = Color.White;
            Icon = Properties.Resources.slydo_icon;

            _lblTitle = new Label
            {
                Text = "Slydo 知识库",
                Font = new Font("微软雅黑", 18, FontStyle.Bold),
                ForeColor = Color.FromArgb(26, 26, 46),
                TextAlign = ContentAlignment.MiddleCenter,
                Location = new Point(0, 20),
                Size = new Size(345, 40),
            };

            _txtUsername = new TextBox
            {
                PlaceholderText = "用户名",
                Location = new Point(30, 80),
                Size = new Size(285, 28),
                Font = new Font("微软雅黑", 12),
            };

            _txtPassword = new TextBox
            {
                PlaceholderText = "密码",
                Location = new Point(30, 120),
                Size = new Size(285, 28),
                Font = new Font("微软雅黑", 12),
                UseSystemPasswordChar = true,
            };

            _btnLogin = new Button
            {
                Text = "登  录",
                Location = new Point(30, 165),
                Size = new Size(285, 36),
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
                Location = new Point(30, 210),
                Size = new Size(285, 30),
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

            if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(password))
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
                        Services.TokenManager.Save(tokenResp.access_token, tokenResp.refresh_token);
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
