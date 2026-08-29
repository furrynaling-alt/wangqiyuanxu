// 往栖缘叙 · 启动器 (C#) — 启动 Node 服务并用 Edge App 模式打开
// 编译: csc /nologo /target:winexe /out:往栖缘叙.exe /r:System.Windows.Forms.dll launcher.cs
using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Threading;

class Launcher {
    static string ExeDir = AppDomain.CurrentDomain.BaseDirectory;
    const string URL = "http://127.0.0.1:3000";

    static bool IsUp() {
        try {
            var req = (HttpWebRequest)WebRequest.Create(URL + "/api/status");
            req.Timeout = 800;
            using (var resp = (HttpWebResponse)req.GetResponse())
                return resp.StatusCode == HttpStatusCode.OK;
        } catch { return false; }
    }

    static void Main() {
        if (!IsUp()) StartServer();
        for (int i = 0; i < 40 && !IsUp(); i++) Thread.Sleep(500);
        OpenBrowser();
    }

    static void StartServer() {
        string node = FindNode();
        if (node == null) {
            System.Windows.Forms.MessageBox.Show("未找到 Node.js。请先安装 Node.js 18+：\nhttps://nodejs.org/", "往栖缘叙");
            return;
        }
        try {
            var psi = new ProcessStartInfo(node, "server.js") {
                WorkingDirectory = ExeDir,
                CreateNoWindow = true,
                UseShellExecute = false
            };
            Process.Start(psi);
        } catch { }
    }

    static string FindNode() {
        string pathEnv = Environment.GetEnvironmentVariable("PATH") ?? "";
        foreach (var dir in pathEnv.Split(';')) {
            try { string f = Path.Combine(dir.Trim(), "node.exe"); if (File.Exists(f)) return f; } catch { }
        }
        string[] roots = {
            @"C:\Program Files\nodejs\node.exe",
            @"C:\Program Files (x86)\nodejs\node.exe",
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "nodejs", "node.exe")
        };
        foreach (var r in roots) if (File.Exists(r)) return r;
        return null;
    }

    static void OpenBrowser() {
        string edge = @"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe";
        if (!File.Exists(edge)) edge = @"C:\Program Files\Microsoft\Edge\Application\msedge.exe";
        try {
            if (File.Exists(edge)) Process.Start(edge, "--app=" + URL + " --window-size=1360,860");
            else Process.Start(URL);
        } catch { }
    }
}
