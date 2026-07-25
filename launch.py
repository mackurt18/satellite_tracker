"""
launch.py  ·  一键启动卫星查看器 Web UI
========================================
为什么需要这个:
  1. satellite_tracker.html 双击打开只能看到源码/或者用 VS Code 渲染
     而不是真正的浏览器(Windows 默认 .html 关联可能被劫持到编辑器)
  2. 就算开了,浏览器 Geolocation API 在 file:// 协议下会被严格拦截
     → 你的位置永远定位不到自己

解决办法:
  这个脚本会:
    - 在 e:\\python code\\卫星\\ 目录里启动一个本地 HTTP 服务(端口 8765)
    - 自动打开你默认浏览器到 http://localhost:8765/satellite_tracker.html
    - 按 Ctrl+C 关闭服务退出

双击 launch.py 即可,或者:
    python launch.py
"""
from __future__ import annotations

import http.server
import socketserver
import webbrowser
import os
import sys
import socket
import threading
from pathlib import Path

# Windows 控制台默认 GBK,会导致 emoji / 中文 print 崩溃.
# 强制 stdout/stderr 用 UTF-8 输出 (Python 3.7+)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

HERE = Path(__file__).resolve().parent
os.chdir(HERE)


def find_free_port(preferred: int = 8765) -> int:
    for port in (preferred, 8766, 8767, 8768, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                if port == 0:
                    raise
    return preferred


class SilentHandler(http.server.SimpleHTTPRequestHandler):
    """和默认 SimpleHTTPRequestHandler 一样,但不打印每条请求日志。"""
    def log_message(self, fmt, *args):
        sys.stderr.write(f"  [HTTP] {self.address_string()} {fmt % args}\n")

    def end_headers(self):
        # 禁用缓存方便调试
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


def main():
    port = find_free_port()
    url = f"http://localhost:{port}/satellite_tracker.html"

    print("=" * 60)
    print("  🛰️  卫星查看器 - 本地 Web 服务")
    print("=" * 60)
    print(f"  目录   : {HERE}")
    print(f"  端口   : {port}")
    print(f"  浏览器 : {url}")
    print("  退出   : 按 Ctrl+C")
    print("=" * 60)

    # Allow socket reuse so we can re-launch quickly
    socketserver.TCPServer.allow_reuse_address = True
    try:
        httpd = socketserver.TCPServer(("127.0.0.1", port), SilentHandler)
    except OSError as e:
        print(f"  ❌ 启动失败: {e}")
        print("  请检查端口是否被占用 (例如 8765 已被其他程序占用)")
        sys.exit(1)

    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    # 等几百毫秒确保 socket 已监听
    import time
    time.sleep(0.3)

    print("\n  正在打开浏览器...")
    try:
        opened = webbrowser.open(url, new=2)  # new=2 = 新标签页 (如支持)
        if not opened:
            print(f"  ⚠️ 自动打开浏览器失败,请手动访问上面这个 URL")
    except Exception as e:
        print(f"  ⚠️ 浏览器异常: {e}")
        print(f"  请手动复制 URL: {url}")

    print("\n  ✨ 服务运行中。 修改 satellite_tracker.html 后按 F5 刷新即可看到。")
    print()

    try:
        # 主线程常驻直到 Ctrl+C. 不依赖 stdin,
        # 这样后台拉起时 stdin 被关闭也不会立刻退出.
        while True:
            import time as _t
            _t.sleep(3600)
    except KeyboardInterrupt:
        print("\n  收到 Ctrl+C ...")
    finally:
        print("  正在关闭服务...")
        try:
            httpd.shutdown()
            httpd.server_close()
        except Exception:
            pass
        print("  👋 服务已停止。再见!")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"启动器异常: {e}")
        try:
            input("按回车键退出...")
        except EOFError:
            import time as _t; _t.sleep(3)
