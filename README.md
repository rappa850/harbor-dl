# Harbor-DL

自托管的个人媒体工作台：下载、订阅作者、录制直播、管理并播放自己的媒体库。后端 FastAPI + SQLite，前端 Vue，MIT 许可。项目仍在开发中，下面如实列出已完成和未完成的部分。

## 现在能做什么

- **下载**：粘贴链接或分享文本，解析元数据与可选格式（基于 yt-dlp），加入队列；下载在独立子进程中运行，可取消、重试；状态为排队 / 下载中 / 处理中 / 已完成 / 失败 / 已取消。支持字幕、缩略图选项，全局代理与按平台保存的 Cookie。
- **媒体库与播放器**：下载的文件自动入库，视频 / 音频 / 图片在线播放，VTT / SRT 字幕，顺序 / 随机 / 单曲循环；图集用专用查看器（轮播 + 背景音乐）。
- **作者订阅**（详见 [docs/subscriptions.md](docs/subscriptions.md)）：
  - **抖音博主**：主页或分享短链接添加，全量同步、增量检查、定时检查、新作品自动下载（视频与图集），下载本身不需要登录。
  - YouTube 频道 / Shorts / 歌单、B 站作者：手动同步与单项下载。
  - 订阅页：订阅列表 + 详情 + 作品封面网格，搜索、状态筛选、批量下载、播放、NFO 编辑、清理缺失记录、导入 / 导出。
  - 平台适配接口：其他平台按同一接口接入。
- **内嵌浏览器登录**（详见 [docs/browser-login.md](docs/browser-login.md)）：在专用的 Chrome 用户目录里登录平台并保存 Cookie；Docker 部署里通过 noVNC 内嵌在页面中。
- **直播**：B 站直播间检测、周期监控、录制流解析、TS 手动 / 自动录制与文件停滞收尾、录制历史与下载。
- **账号与安全**：首次启动创建管理员，会话登录，可创建 API Token（`X-API-Token` 或 `Authorization: Bearer`）。

## 还没有做

直播的录制时段、分段、后处理、弹幕与其他平台；订阅的其他平台适配、抖音点赞 / 合集 / 批量添加；通知与机器人；AI 助手与精彩片段；Cookie 自动更新；多用户角色；NFO 自动生成。完整清单见 [docs/status.md](docs/status.md)。

## 运行

需要 Python 3.11+、Node.js；FFmpeg 用于合并音视频；Chrome 用于内嵌登录和抖音匿名取详情。

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
cd frontend
npm install
npm run build
cd ..
.venv/Scripts/python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8765
```

（Linux / macOS 把 `.venv/Scripts/python.exe` 换成 `.venv/bin/python`。）打开 `http://127.0.0.1:8765`，第一次访问时创建管理员账号。

| 环境变量 | 作用 |
| --- | --- |
| `HARBOR_DATA_DIR` | 数据目录（数据库、下载、录制、专用浏览器用户目录），默认 `./var` |
| `HARBOR_CHROME` | Chrome / Chromium 可执行文件路径，默认自动查找 |
| `HARBOR_BROWSER_MODE` | `desktop`（默认，弹出可见窗口）或 `docker`（虚拟显示 + noVNC） |
| `HARBOR_DISPLAY` / `HARBOR_NOVNC_DIR` / `HARBOR_VNC_WS` | Docker 模式的显示号、noVNC 静态目录、VNC WebSocket 地址 |

Docker 部署见 [docs/deployment.md](docs/deployment.md)。

## 测试

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests
cd frontend; node --test tests/playback-policy.test.js
```

后端测试不访问真实媒体平台（平台响应使用本地桩），内嵌浏览器相关测试会启动本机 Chrome。

## 安全提示

Cookie 与代理凭据目前明文保存在本地数据库中，普通接口不会返回其内容；请勿把数据目录或服务直接暴露到公网，对外使用请放在带 TLS 的反向代理之后。第三方组件的许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 许可

[MIT](LICENSE)。
