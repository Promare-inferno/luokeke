# 洛可可 · 后端
#
# 一个文件干两件事：
#   1. 把 web/ 里的页面和 assets/ 里的图发给浏览器
#   2. 收到 /chat 就把你说的话交给模型，再把她的回话送回页面
#
# 跑起来：
#   ..\.venv\Scripts\python.exe server.py
# 然后浏览器打开：
#   http://127.0.0.1:8000
#
# 注意：不要双击 index.html。用 file:// 打开的话，
# 页面连不到这个服务，她永远说不出话。

import os
import sys
import json
import time
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests


HERE   = os.path.dirname(os.path.abspath(__file__))
WEB    = os.path.join(HERE, "web")
ASSETS = os.path.join(HERE, "assets")
LOG    = os.path.join(HERE, "luokeke.log")

PORT      = 8000
MAX_KEEP  = 20    # 每次发给模型，本子最多带几条
MAX_STORE = 120   # 内存里最多留几条，防止越聊越占地方

API   = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"


# ── 钥匙 ──────────────────────────────────────────────────────
# 先看环境变量。没有就去注册表翻一次。
# 这样不管你从哪个窗口启动，都不用重开 cmd。
def find_key():
    k = os.environ.get("DEEPSEEK_API_KEY")
    if k:
        return k.strip()
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as r:
            v, _ = winreg.QueryValueEx(r, "DEEPSEEK_API_KEY")
            return (v or "").strip()
    except Exception:
        return ""


KEY = find_key()

if not KEY:
    print("没找到 DEEPSEEK_API_KEY。先跑一次：")
    print('  setx DEEPSEEK_API_KEY "sk-你的key"')
    print("然后重开一个窗口。")
    raise SystemExit

HEADERS = {
    "Authorization": f"Bearer {KEY}",
    "Content-Type": "application/json",
}


# ── 人格 ──────────────────────────────────────────────────────
# 从同目录的 persona.py 里取 SYSTEM。
# 没有就先用一段最简的顶上，页面照样能聊。
def load_persona():
    try:
        sys.path.insert(0, HERE)
        import persona
        text = (getattr(persona, "SYSTEM", "") or "").strip()
        if text:
            return text, "persona.py"
    except Exception as e:
        print(f"persona.py 读不了（{e}），先用兜底的一句。")

    return (
        "你是洛可可，来自维多利亚时代的九尾狐，托拉的创始人。"
        "用「阁下」称呼对方，偶尔说「唔姆」，语气居高临下但不刻薄。"
        "回复控制在三句以内。",
        "兜底（还没有 persona.py）",
    )


SYSTEM, PERSONA_FROM = load_persona()


# ── 日志 ──────────────────────────────────────────────────────
def log(text):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] {text}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ── 本子 ──────────────────────────────────────────────────────
# 现在只有你一个人聊，一个列表就够。
# 以后要做多会话，把这里换成 {会话id: 列表}。
HISTORY = []


def trim(msgs, keep):
    """留最近 keep 条，并且保证开头是 user。
    留一个 assistant 或半截开头，模型容易接错话。"""
    if len(msgs) <= keep:
        return list(msgs)
    tail = msgs[-(keep - 1):]
    while tail and tail[0].get("role") != "user":
        tail.pop(0)
    return tail


def ask(text):
    """把一句话送出去，等一句回话。失败重试三次。"""
    HISTORY.append({"role": "user", "content": text})

    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM}] + trim(HISTORY, MAX_KEEP),
        "temperature": 0.9,
    }

    err = ""
    for i in range(3):
        try:
            r = requests.post(API, headers=HEADERS, json=payload, timeout=60)

            if r.status_code == 200:
                reply = r.json()["choices"][0]["message"]["content"].strip()
                HISTORY.append({"role": "assistant", "content": reply})
                del HISTORY[:-MAX_STORE]        # 只留最近的那一批
                log(f"她回了 {len(reply)} 个字")
                return reply

            err = f"HTTP {r.status_code} · {r.text[:150]}"
            # 钥匙错、额度空、请求体不对，重试也没用，直接出来
            if r.status_code in (400, 401, 402, 403, 404):
                break

        except requests.RequestException as e:
            err = f"{type(e).__name__} · {e}"

        time.sleep(1.5 * (i + 1))               # 等一等再试，别把接口惹烦

    HISTORY.pop()                               # 这句没送成，从本子上撤掉
    raise RuntimeError(err or "不知道哪儿出错了")


# ── HTTP ──────────────────────────────────────────────────────
MIME = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".gif":  "image/gif",
    ".webp": "image/webp",
    ".svg":  "image/svg+xml",
    ".ico":  "image/x-icon",
    ".woff2": "font/woff2",
}


class Server(ThreadingHTTPServer):
    """独占 8000。

    Windows 上 http.server 默认开着 SO_REUSEADDR，
    后果是两个 server.py 能同时占住同一个端口，谁都不报错，
    浏览器连过来随机落到其中一个——表现就是时好时坏、
    明明是开着的却说「连不上后台」。
    锁死之后，第二个进程启动就会直接失败，一眼看得出来。
    """

    allow_reuse_address = False

    def server_bind(self):
        if os.name == "nt":
            import socket
            self.socket.setsockopt(socket.SOL_SOCKET,
                                   socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    server_version = "Luokeke/0.1"

    def log_message(self, fmt, *args):
        pass                                    # 默认的访问日志太吵，关掉

    # ---- 发文件 ----
    def do_GET(self):
        rel = self.path.split("?")[0].lstrip("/") or "index.html"

        # ---- 擦本子 ----
        # 浏览器打开 /reset，她就忘掉之前所有的话。
        # 只清内存里的 HISTORY，日志留着。
        if rel == "reset":
            n = len(HISTORY)
            HISTORY.clear()
            log(f"本子擦干净了，清掉 {n} 条")
            self.send_json({"ok": True, "cleared": n})
            return

        if rel.startswith("assets/"):
            root, rel = ASSETS, rel[len("assets/"):]
        else:
            root = WEB

        full = os.path.abspath(os.path.join(root, rel))

        # 防止 ../ 爬到目录外面去
        if not full.startswith(root) or not os.path.isfile(full):
            self.send_error(404, "not found")
            return

        with open(full, "rb") as f:
            data = f.read()

        self.send_response(200)
        self.send_header("Content-Type", MIME.get(os.path.splitext(full)[1].lower(),
                                                  "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")   # 改了文件刷新就能看见
        self.end_headers()
        self.wfile.write(data)

    # ---- 接话 ----
    def do_POST(self):
        if self.path.split("?")[0] != "/chat":
            self.send_error(404, "not found")
            return

        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            text = (body.get("text") or "").strip()
        except Exception:
            self.send_json({"reply": "（没读懂你发过来的东西）", "error": True}, 400)
            return

        if not text:
            self.send_json({"reply": "……阁下，你一个字都没说。", "error": True}, 400)
            return

        log(f"他说：{text}")

        try:
            self.send_json({"reply": ask(text)})
        except RuntimeError as e:
            log(f"没成：{e}")
            self.send_json({"reply": f"（这边出了岔子：{e}）", "error": True}, 502)

    # ---- 小工具 ----
    def send_json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def main():
    print("─" * 46)
    print("洛可可 · 后端")
    print(f"钥匙：{'找到了' if KEY else '没找到'}")
    print(f"人格：{PERSONA_FROM}")
    print(f"打开：http://127.0.0.1:{PORT}")
    print("Ctrl+C 停")
    print("─" * 46)

    try:
        srv = Server(("127.0.0.1", PORT), Handler)
    except OSError:
        print(f"端口 {PORT} 上已经有一个在跑了，这个不起。")
        print("要换掉它，先看是谁：")
        print(f"  netstat -ano | findstr :{PORT}")
        print("再按最后一列那个 PID 杀掉：")
        print("  taskkill /PID 那个PID /F")
        raise SystemExit

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n门关上啦。")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
