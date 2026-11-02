from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit


LOGIN_PAGE = """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>零代码测试示例 - 登录</title>
    <style>
      :root { color-scheme: light; font-family: system-ui, sans-serif; }
      body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #eef2f3; color: #17212b; }
      main { width: min(360px, calc(100vw - 48px)); padding: 32px; background: #fff; border: 1px solid #cfd8dc; border-radius: 8px; }
      h1 { margin: 0 0 8px; font-size: 24px; }
      p { margin: 0 0 24px; color: #52606d; }
      label { display: grid; gap: 6px; margin-bottom: 16px; font-weight: 600; }
      input { min-height: 40px; padding: 0 10px; border: 1px solid #aab7c4; border-radius: 4px; font: inherit; }
      button { width: 100%; min-height: 42px; border: 0; border-radius: 4px; background: #0b6b55; color: #fff; font: inherit; font-weight: 700; cursor: pointer; }
      [role="alert"] { min-height: 20px; margin-top: 12px; color: #b42318; }
    </style>
  </head>
  <body>
    <main>
      <h1>零代码测试示例</h1>
      <p>使用自然语言测试卡驱动确定性回放。</p>
      <form id="login-form">
        <label>用户名 <input data-testid="login-username" autocomplete="username" /></label>
        <label>密码 <input data-testid="login-password" type="password" autocomplete="current-password" /></label>
        <button data-testid="login-submit" type="submit">登录</button>
        <div role="alert" data-testid="login-error"></div>
      </form>
      <p><a href="/home">预览首页</a></p>
    </main>
    <script>
      document.getElementById("login-form").addEventListener("submit", (event) => {
        event.preventDefault();
        const username = document.querySelector('[data-testid="login-username"]').value;
        const password = document.querySelector('[data-testid="login-password"]').value;
        if (username === "demo" && password === "demo123") {
          window.location.assign("/home");
          return;
        }
        document.querySelector('[data-testid="login-error"]').textContent = "用户名或密码错误";
      });
    </script>
  </body>
</html>
"""

HOME_PAGE = """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>零代码测试示例 - 首页</title>
    <style>
      :root { color-scheme: light; font-family: system-ui, sans-serif; }
      body { margin: 0; min-height: 100vh; background: #eef2f3; color: #17212b; }
      header { display: flex; align-items: center; justify-content: space-between; padding: 20px 32px; background: #173f35; color: #fff; }
      main { padding: 40px 32px; }
      button { min-height: 38px; padding: 0 16px; border: 1px solid #fff; border-radius: 4px; background: transparent; color: #fff; font: inherit; cursor: pointer; }
      h1 { margin: 0 0 12px; }
    </style>
  </head>
  <body>
    <header>
      <strong>零代码测试示例</strong>
      <button data-testid="logout" onclick="window.location.assign('/login')">退出登录</button>
    </header>
    <main>
      <h1>欢迎回来</h1>
      <p>登录流程已经完成，可以继续执行其他测试契约。</p>
    </main>
  </body>
</html>
"""


@dataclass
class DemoServer:
    url: str
    _server: ThreadingHTTPServer
    _thread: threading.Thread

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


class DemoRequestHandler(BaseHTTPRequestHandler):
    server_version = "AI4TestsDemo/0.2"

    def do_GET(self) -> None:
        path = urlsplit(self.path).path

        if path == "/login":
            self.send_html(LOGIN_PAGE)
            return
        if path == "/home":
            self.send_html(HOME_PAGE)
            return
        if path == "/health":
            self.send_json({"ok": True})
            return

        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", "/login")
        self.end_headers()

    def send_html(self, content: str) -> None:
        self._write(
            HTTPStatus.OK,
            "text/html; charset=utf-8",
            content.encode("utf-8"),
        )

    def send_json(self, payload: dict[str, Any]) -> None:
        self._write(
            HTTPStatus.OK,
            "application/json; charset=utf-8",
            json.dumps(payload).encode("utf-8"),
        )

    def _write(
        self,
        status: HTTPStatus,
        content_type: str,
        body: bytes,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def start_server(
    port: int = 4173,
    host: str = "127.0.0.1",
) -> DemoServer:
    server = ThreadingHTTPServer((host, port), DemoRequestHandler)
    thread = threading.Thread(
        target=server.serve_forever,
        name="demo-login-server",
        daemon=True,
    )
    thread.start()
    return DemoServer(
        url=f"http://{host}:{server.server_port}",
        _server=server,
        _thread=thread,
    )


if __name__ == "__main__":
    demo = start_server(port=int(os.environ.get("PORT", "4173")))
    print(f"Demo app listening at {demo.url}", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        demo.close()

