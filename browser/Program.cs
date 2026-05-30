using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace DSComfyUIBrowser;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        var options = BrowserOptions.Parse(args);
        Application.Run(new BrowserForm(options));
    }
}

internal sealed class BrowserForm : Form
{
    private static readonly CoreWebView2BrowsingDataKinds VolatileCacheKinds =
        CoreWebView2BrowsingDataKinds.DiskCache
        | CoreWebView2BrowsingDataKinds.CacheStorage
        | CoreWebView2BrowsingDataKinds.ServiceWorkers;

    private readonly BrowserOptions _options;
    private readonly WebView2 _webView = new();
    private readonly Button _refreshButton = new();
    private readonly Button _cleanCacheButton = new();
    private readonly System.Windows.Forms.Timer _hoverTimer = new();
    private string _targetUrl;
    private DateTime _refreshVisibleUntil = DateTime.MinValue;
    private bool _allowClose;

    public BrowserForm(BrowserOptions options)
    {
        _options = options;
        _targetUrl = NormalizeLocalUrl(options.Url);
        Text = options.Title;
        WindowState = FormWindowState.Maximized;
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = options.DarkTheme ? Color.FromArgb(32, 32, 32) : Color.FromArgb(243, 244, 246);
        Icon = LoadAppIcon();
        ConfigureRefreshButton();

        Load += async (_, _) => await StartDedicatedAsync();
    }

    private async Task StartDedicatedAsync()
    {
        await InitializeBrowserAsync();
    }

    private async Task InitializeBrowserAsync()
    {
        Directory.CreateDirectory(_options.UserDataFolder);
        var environment = await CoreWebView2Environment.CreateAsync(
            browserExecutableFolder: BrowserRuntimeFolder(),
            userDataFolder: _options.UserDataFolder,
            options: new CoreWebView2EnvironmentOptions("--disable-features=Translate --disable-sync --disable-background-networking --disable-http-cache")
        );
        await _webView.EnsureCoreWebView2Async(environment);

        var settings = _webView.CoreWebView2.Settings;
        settings.AreDevToolsEnabled = false;
        settings.AreDefaultScriptDialogsEnabled = true;
        settings.AreDefaultContextMenusEnabled = true;
        settings.IsStatusBarEnabled = false;
        settings.IsZoomControlEnabled = true;
        settings.IsGeneralAutofillEnabled = false;
        settings.IsPasswordAutosaveEnabled = false;

        _webView.CoreWebView2.DownloadStarting += OnDownloadStarting;
        _webView.CoreWebView2.NewWindowRequested += OnNewWindowRequested;
        _webView.CoreWebView2.ScriptDialogOpening += OnScriptDialogOpening;
        _webView.CoreWebView2.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
        _webView.CoreWebView2.WebResourceRequested += OnWebResourceRequested;
        await ClearVolatileCacheAsync();
        _webView.Source = new Uri(_targetUrl);
        Controls.Clear();
        _webView.Dock = DockStyle.Fill;
        Controls.Add(_webView);
        Controls.Add(_refreshButton);
        Controls.Add(_cleanCacheButton);
        UpdateOverlayButtonPositions();
        _refreshButton.BringToFront();
        _cleanCacheButton.BringToFront();
        _hoverTimer.Start();
        ApplyDarkTitleBar(Handle, _options.DarkTheme);
    }

    private void ConfigureRefreshButton()
    {
        StyleOverlayButton(_refreshButton, "Refresh");
        StyleOverlayButton(_cleanCacheButton, "Clean Cache");
        _refreshButton.Click += (_, _) =>
        {
            if (ThemedDialog.ShowConfirm(
                    this,
                    "Refresh Dedicated Window",
                    "Refresh the dedicated window?",
                    _options.DarkTheme,
                    confirmText: "Yes",
                    cancelText: "No"))
            {
                _webView.Reload();
            }
        };
        _cleanCacheButton.Click += async (_, _) =>
        {
            if (!ThemedDialog.ShowConfirm(
                    this,
                    "Clean Dedicated Cache",
                    "Clear the cache for this dedicated instance?",
                    _options.DarkTheme,
                    confirmText: "Yes",
                    cancelText: "No",
                    destructive: true,
                    cancelAccent: true))
            {
                return;
            }
            try
            {
                await ClearVolatileCacheAsync(throwOnFailure: true);
                _webView.Reload();
            }
            catch (Exception exc)
            {
                ThemedDialog.ShowInfo(this, "Clean Cache Failed", $"Could not clear the cache: {exc.Message}", _options.DarkTheme);
            }
        };
        _refreshButton.Resize += (_, _) => RoundControl(_refreshButton, 10);
        _cleanCacheButton.Resize += (_, _) => RoundControl(_cleanCacheButton, 10);

        _hoverTimer.Interval = 140;
        _hoverTimer.Tick += (_, _) =>
        {
            var point = PointToClient(Cursor.Position);
            var inHotCorner = point.X >= 0 && point.Y >= 0 && point.X <= 36 && point.Y <= 36;
            var overButton = _refreshButton.Visible && _refreshButton.Bounds.Contains(point);
            var overCleanCache = _cleanCacheButton.Visible && _cleanCacheButton.Bounds.Contains(point);
            var shouldShow = inHotCorner || overButton || overCleanCache || _refreshButton.Visible && _refreshVisibleUntil > DateTime.UtcNow;
            if (inHotCorner || overButton || overCleanCache)
            {
                _refreshVisibleUntil = DateTime.UtcNow.AddSeconds(3);
            }
            if (_refreshButton.Visible != shouldShow)
            {
                _refreshButton.Visible = shouldShow;
                _cleanCacheButton.Visible = shouldShow;
                if (shouldShow)
                {
                    UpdateOverlayButtonPositions();
                    _refreshButton.BringToFront();
                    _cleanCacheButton.BringToFront();
                }
            }
        };
        Resize += (_, _) => UpdateOverlayButtonPositions();
        RoundControl(_refreshButton, 10);
        RoundControl(_cleanCacheButton, 10);
    }

    private void StyleOverlayButton(Button button, string text)
    {
        button.Text = text;
        button.Width = 92;
        button.Height = 26;
        button.Visible = false;
        button.FlatStyle = FlatStyle.Flat;
        button.Font = new Font("Segoe UI", 8.5f);
        button.BackColor = _options.DarkTheme ? Color.FromArgb(48, 50, 54) : Color.FromArgb(238, 240, 244);
        button.ForeColor = _options.DarkTheme ? Color.White : Color.FromArgb(20, 24, 30);
        button.FlatAppearance.BorderSize = 0;
    }

    private void UpdateOverlayButtonPositions()
    {
        _refreshButton.Left = 12;
        _refreshButton.Top = 12;
        _cleanCacheButton.Left = 12;
        _cleanCacheButton.Top = _refreshButton.Bottom + 6;
    }

    private static void RoundControl(Control control, int radius)
    {
        if (control.Width <= 0 || control.Height <= 0)
        {
            return;
        }
        control.Region?.Dispose();
        control.Region = Region.FromHrgn(CreateRoundRectRgn(0, 0, control.Width + 1, control.Height + 1, radius, radius));
    }

    private static string NormalizeLocalUrl(string url)
    {
        var cleaned = string.IsNullOrWhiteSpace(url) ? "http://127.0.0.1:8188" : url.Trim();
        if (!cleaned.StartsWith("http://", StringComparison.OrdinalIgnoreCase)
            && !cleaned.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
        {
            cleaned = "http://" + cleaned;
        }
        return cleaned.TrimEnd('/');
    }

    private static string? BrowserRuntimeFolder()
    {
        var localRuntime = Path.Combine(AppContext.BaseDirectory, "runtime");
        return Directory.Exists(localRuntime) ? localRuntime : null;
    }

    private async Task ClearVolatileCacheAsync(bool throwOnFailure = false)
    {
        try
        {
            await _webView.CoreWebView2.Profile.ClearBrowsingDataAsync(VolatileCacheKinds);
        }
        catch
        {
            if (throwOnFailure)
            {
                throw;
            }
        }
    }

    private void OnWebResourceRequested(object? sender, CoreWebView2WebResourceRequestedEventArgs e)
    {
        if (!IsTargetComfyRequest(e.Request.Uri))
        {
            return;
        }

        try
        {
            e.Request.Headers.SetHeader("Cache-Control", "no-cache, no-store, must-revalidate");
            e.Request.Headers.SetHeader("Pragma", "no-cache");
            e.Request.Headers.SetHeader("Expires", "0");
        }
        catch
        {
        }
    }

    private bool IsTargetComfyRequest(string requestUrl)
    {
        if (!Uri.TryCreate(requestUrl, UriKind.Absolute, out var requestUri)
            || !Uri.TryCreate(_targetUrl, UriKind.Absolute, out var targetUri))
        {
            return false;
        }

        return string.Equals(requestUri.Scheme, targetUri.Scheme, StringComparison.OrdinalIgnoreCase)
            && string.Equals(requestUri.Host, targetUri.Host, StringComparison.OrdinalIgnoreCase)
            && requestUri.Port == targetUri.Port;
    }

    private void OnNewWindowRequested(object? sender, CoreWebView2NewWindowRequestedEventArgs e)
    {
        if (!string.IsNullOrWhiteSpace(e.Uri))
        {
            try
            {
                System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(e.Uri) { UseShellExecute = true });
            }
            catch
            {
            }
        }
        e.Handled = true;
    }

    private void OnDownloadStarting(object? sender, CoreWebView2DownloadStartingEventArgs e)
    {
        using var dialog = new SaveFileDialog();
        dialog.Title = "Save file";
        dialog.InitialDirectory = LastDownloadFolder();
        dialog.FileName = SafeFileName(Path.GetFileName(e.ResultFilePath));
        if (dialog.ShowDialog(this) != DialogResult.OK)
        {
            e.Cancel = true;
            return;
        }
        e.ResultFilePath = dialog.FileName;
        StoreLastDownloadFolder(Path.GetDirectoryName(dialog.FileName) ?? LastDownloadFolder());
        e.Handled = true;
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (!_allowClose)
        {
            var result = ThemedDialog.ShowConfirm(
                this,
                "Close Dedicated Window",
                "Closing this window will also close the running instance. Do you want to proceed?",
                _options.DarkTheme,
                confirmText: "Yes",
                cancelText: "No",
                destructive: true,
                cancelAccent: true
            );
            if (!result)
            {
                e.Cancel = true;
                return;
            }
            _allowClose = true;
        }
        _hoverTimer.Stop();
        base.OnFormClosing(e);
    }

    private void OnScriptDialogOpening(object? sender, CoreWebView2ScriptDialogOpeningEventArgs e)
    {
        switch (e.Kind)
        {
            case CoreWebView2ScriptDialogKind.Alert:
                ThemedDialog.ShowInfo(this, "ComfyUI", e.Message, _options.DarkTheme);
                e.Accept();
                break;
            case CoreWebView2ScriptDialogKind.Confirm:
                if (ThemedDialog.ShowConfirm(this, "ComfyUI", e.Message, _options.DarkTheme))
                {
                    e.Accept();
                }
                break;
            case CoreWebView2ScriptDialogKind.Prompt:
                if (ThemedDialog.ShowPrompt(this, "ComfyUI", e.Message, e.DefaultText, _options.DarkTheme, out var value))
                {
                    e.ResultText = value;
                    e.Accept();
                }
                break;
            default:
                ThemedDialog.ShowInfo(this, "ComfyUI", e.Message, _options.DarkTheme);
                e.Accept();
                break;
        }
    }

    protected override void WndProc(ref Message m)
    {
        base.WndProc(ref m);
        if (m.Msg is 0x0001 or 0x0083 or 0x031A)
        {
            ApplyDarkTitleBar(Handle, _options.DarkTheme);
        }
    }

    private string LastDownloadFolder()
    {
        try
        {
            if (File.Exists(_options.ConfigPath))
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(_options.ConfigPath));
                if (doc.RootElement.TryGetProperty("preferences", out var prefs)
                    && prefs.TryGetProperty("instances", out var instances)
                    && instances.TryGetProperty(_options.InstanceKey, out var settings)
                    && settings.TryGetProperty("last_download_folder", out var folderElement))
                {
                    var folder = folderElement.GetString();
                    if (!string.IsNullOrWhiteSpace(folder) && Directory.Exists(folder))
                    {
                        return folder;
                    }
                }
            }
        }
        catch
        {
        }
        var desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        return Directory.Exists(desktop) ? desktop : Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
    }

    private void StoreLastDownloadFolder(string folder)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(_options.ConfigPath) || string.IsNullOrWhiteSpace(_options.InstanceKey))
            {
                return;
            }
            var payload = File.Exists(_options.ConfigPath)
                ? JsonSerializer.Deserialize<Dictionary<string, object?>>(File.ReadAllText(_options.ConfigPath)) ?? new()
                : new Dictionary<string, object?>();
            var json = JsonSerializer.SerializeToNode(payload)!.AsObject();
            var preferences = json["preferences"]?.AsObject() ?? new System.Text.Json.Nodes.JsonObject();
            json["preferences"] = preferences;
            var instances = preferences["instances"]?.AsObject() ?? new System.Text.Json.Nodes.JsonObject();
            preferences["instances"] = instances;
            var settings = instances[_options.InstanceKey]?.AsObject() ?? new System.Text.Json.Nodes.JsonObject();
            instances[_options.InstanceKey] = settings;
            settings["last_download_folder"] = folder;
            File.WriteAllText(_options.ConfigPath, json.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
        }
        catch
        {
        }
    }

    private static string SafeFileName(string? name)
    {
        var fallback = string.IsNullOrWhiteSpace(name) ? "download" : name;
        foreach (var invalid in Path.GetInvalidFileNameChars())
        {
            fallback = fallback.Replace(invalid, '_');
        }
        return string.IsNullOrWhiteSpace(fallback) ? "download" : fallback;
    }

    private static Icon? LoadAppIcon()
    {
        var icon = Path.Combine(AppContext.BaseDirectory, "DSCUIM.ico");
        return File.Exists(icon) ? new Icon(icon) : null;
    }

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int attrValue, int attrSize);

    [DllImport("gdi32.dll")]
    private static extern IntPtr CreateRoundRectRgn(int left, int top, int right, int bottom, int width, int height);

    private static void ApplyDarkTitleBar(IntPtr handle, bool dark)
    {
        if (OperatingSystem.IsWindowsVersionAtLeast(10, 0, 17763))
        {
            var value = dark ? 1 : 0;
            _ = DwmSetWindowAttribute(handle, 20, ref value, sizeof(int));
            _ = DwmSetWindowAttribute(handle, 19, ref value, sizeof(int));
        }
    }
}

internal static class ThemedDialog
{
    public static void ShowInfo(IWin32Window owner, string title, string message, bool dark)
    {
        using var dialog = CreateBaseDialog(owner, title, message, dark);
        var okButton = CreateButton("OK", dark, accent: true);
        okButton.DialogResult = DialogResult.OK;
        AddButtons(dialog, okButton);
        dialog.AcceptButton = okButton;
        _ = dialog.ShowDialog(owner);
    }

    public static bool ShowConfirm(
        IWin32Window owner,
        string title,
        string message,
        bool dark,
        string confirmText = "OK",
        string cancelText = "Cancel",
        bool destructive = false,
        bool cancelAccent = false)
    {
        using var dialog = CreateBaseDialog(owner, title, message, dark);
        var cancelButton = CreateButton(cancelText, dark, accent: cancelAccent);
        var confirmButton = CreateButton(confirmText, dark, accent: !destructive, destructive: destructive);
        cancelButton.DialogResult = DialogResult.Cancel;
        confirmButton.DialogResult = DialogResult.OK;
        AddButtons(dialog, cancelButton, confirmButton);
        dialog.AcceptButton = confirmButton;
        dialog.CancelButton = cancelButton;
        return dialog.ShowDialog(owner) == DialogResult.OK;
    }

    public static bool ShowPrompt(IWin32Window owner, string title, string message, string defaultText, bool dark, out string result)
    {
        using var dialog = CreateBaseDialog(owner, title, message, dark);
        var input = new TextBox
        {
            Text = defaultText,
            Width = 360,
            BorderStyle = BorderStyle.FixedSingle,
            BackColor = dark ? Color.FromArgb(39, 42, 45) : Color.White,
            ForeColor = dark ? Color.White : Color.FromArgb(20, 20, 20),
            Font = new Font("Segoe UI", 10f),
            Margin = new Padding(24, 0, 24, 12)
        };
        var layout = (TableLayoutPanel)dialog.Controls[0];
        layout.Controls.Add(input, 0, 2);
        var cancelButton = CreateButton("Cancel", dark);
        var okButton = CreateButton("OK", dark, accent: true);
        cancelButton.DialogResult = DialogResult.Cancel;
        okButton.DialogResult = DialogResult.OK;
        AddButtons(dialog, cancelButton, okButton);
        dialog.AcceptButton = okButton;
        dialog.CancelButton = cancelButton;
        var accepted = dialog.ShowDialog(owner) == DialogResult.OK;
        result = accepted ? input.Text : "";
        return accepted;
    }

    private static Form CreateBaseDialog(IWin32Window owner, string title, string message, bool dark)
    {
        var dialog = new Form
        {
            Text = title,
            FormBorderStyle = FormBorderStyle.None,
            StartPosition = FormStartPosition.CenterParent,
            MinimizeBox = false,
            MaximizeBox = false,
            ShowInTaskbar = false,
            ClientSize = new Size(460, 150),
            BackColor = dark ? Color.FromArgb(31, 31, 31) : Color.FromArgb(245, 246, 248),
            ForeColor = dark ? Color.White : Color.FromArgb(22, 24, 28),
            Font = new Font("Segoe UI", 10f)
        };
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
            Padding = new Padding(26, 24, 26, 18),
            BackColor = dialog.BackColor
        };
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        var messageLabel = new Label
        {
            Text = message,
            Dock = DockStyle.Fill,
            Font = new Font("Segoe UI", 10f),
            ForeColor = dark ? Color.FromArgb(226, 226, 226) : Color.FromArgb(38, 41, 46),
            Margin = new Padding(0, 0, 0, 18)
        };
        layout.Controls.Add(messageLabel, 0, 0);
        dialog.Controls.Add(layout);
        dialog.Paint += (_, e) =>
        {
            using var pen = new Pen(dark ? Color.FromArgb(62, 62, 66) : Color.FromArgb(210, 214, 220));
            e.Graphics.DrawRectangle(pen, 0, 0, dialog.Width - 1, dialog.Height - 1);
        };
        dialog.Shown += (_, _) => RoundDialog(dialog, 16);
        dialog.Resize += (_, _) => RoundDialog(dialog, 16);
        return dialog;
    }

    private static Button CreateButton(string text, bool dark, bool accent = false, bool destructive = false)
    {
        var button = new Button
        {
            Text = text,
            Width = 128,
            Height = 34,
            FlatStyle = FlatStyle.Flat,
            Font = new Font("Segoe UI", 9.5f),
            Margin = new Padding(8, 0, 0, 0)
        };
        button.FlatAppearance.BorderSize = 0;
        button.Resize += (_, _) => RoundControl(button, 10);
        if (destructive)
        {
            button.BackColor = Color.FromArgb(239, 68, 68);
            button.ForeColor = Color.White;
        }
        else if (accent)
        {
            button.BackColor = Color.FromArgb(124, 84, 245);
            button.ForeColor = Color.White;
        }
        else
        {
            button.BackColor = dark ? Color.FromArgb(70, 72, 76) : Color.FromArgb(224, 226, 230);
            button.ForeColor = dark ? Color.White : Color.FromArgb(25, 28, 34);
        }
        RoundControl(button, 10);
        return button;
    }

    private static void AddButtons(Form dialog, params Button[] buttons)
    {
        var layout = (TableLayoutPanel)dialog.Controls[0];
        var panel = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.RightToLeft,
            Height = 38,
            Margin = new Padding(0),
            BackColor = dialog.BackColor
        };
        foreach (var button in buttons.Reverse())
        {
            panel.Controls.Add(button);
        }
        layout.Controls.Add(panel, 0, 2);
    }

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int attrValue, int attrSize);

    [DllImport("gdi32.dll")]
    private static extern IntPtr CreateRoundRectRgn(int left, int top, int right, int bottom, int width, int height);

    private static void RoundDialog(Form dialog, int radius)
    {
        dialog.Region?.Dispose();
        dialog.Region = Region.FromHrgn(CreateRoundRectRgn(0, 0, dialog.Width + 1, dialog.Height + 1, radius, radius));
    }

    private static void RoundControl(Control control, int radius)
    {
        if (control.Width <= 0 || control.Height <= 0)
        {
            return;
        }
        control.Region?.Dispose();
        control.Region = Region.FromHrgn(CreateRoundRectRgn(0, 0, control.Width + 1, control.Height + 1, radius, radius));
    }

    private static void ApplyDarkTitleBar(IntPtr handle, bool dark)
    {
        if (OperatingSystem.IsWindowsVersionAtLeast(10, 0, 17763))
        {
            var value = dark ? 1 : 0;
            _ = DwmSetWindowAttribute(handle, 20, ref value, sizeof(int));
            _ = DwmSetWindowAttribute(handle, 19, ref value, sizeof(int));
        }
    }
}

internal sealed record BrowserOptions(
    string Url,
    string Title,
    string UserDataFolder,
    string ConfigPath,
    string InstanceKey,
    bool DarkTheme)
{
    public static BrowserOptions Parse(string[] args)
    {
        string ValueAfter(string name, string fallback = "")
        {
            var index = Array.IndexOf(args, name);
            return index >= 0 && index + 1 < args.Length ? args[index + 1] : fallback;
        }

        return new BrowserOptions(
            Url: ValueAfter("--url", "http://127.0.0.1:8188"),
            Title: ValueAfter("--title", "ComfyUI Dedicated"),
            UserDataFolder: ValueAfter("--user-data-folder", Path.Combine(AppContext.BaseDirectory, "profile")),
            ConfigPath: ValueAfter("--config-path"),
            InstanceKey: ValueAfter("--instance-key"),
            DarkTheme: string.Equals(ValueAfter("--theme", "dark"), "dark", StringComparison.OrdinalIgnoreCase)
        );
    }
}
