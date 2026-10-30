# 洛可可 · 会说话的看板娘

一个本地跑的角色对话页面。左边是立绘，底下是对话，说话的对象是维多利亚时代的九尾狐洛可可。

前端一个 `index.html`，后端一个 `server.py`，人格单独放在 `persona.py` 里。

## 结构

```
luokeke/
├─ assets/bg.jpg          立绘背景
├─ web/index.html         整个页面：样式、结构、脚本都在这一个文件里
├─ server.py              本地服务 + 转发到模型
├─ persona.py             角色人格，改完重启才生效
└─ _洛可可台词原文.txt     角色台词素材
```

## 跑起来

需要 Python 3 和一个 DeepSeek API key。

```bat
setx DEEPSEEK_API_KEY "sk-你的key"
```

关掉窗口重开一个，然后：

```bat
cd luokeke
..\.venv\Scripts\python.exe server.py
```

看到 `打开：http://127.0.0.1:8000` 就成了。浏览器打开这个地址。

**别双击 `index.html`。** 用 `file://` 打开时页面找不到后端，她会一直说连不上。

## 两个接口

| 接口 | 作用 |
| --- | --- |
| `POST /chat` | 收 `{"text": "..."}`，回 `{"reply": "..."}` |
| `GET /reset` | 清空对话记忆，回 `{"ok": true, "cleared": N}` |

记忆只存在内存里（`server.py` 的 `HISTORY` 列表），进程一停就没了。每次发给模型只带最近 20 条。

## 端口被占了

`server.py` 用了独占绑定，第二个进程会直接报错退出，不会再出现两个后台抢同一个端口的情况。真要清掉旧的：

```bat
netstat -ano | findstr :8000
taskkill /PID 那个PID /F
```
