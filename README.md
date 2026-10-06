# Harbor-DL

[![CI](https://github.com/rappa850/harbor-dl/actions/workflows/ci.yml/badge.svg)](https://github.com/rappa850/harbor-dl/actions/workflows/ci.yml)
[![Docker](https://github.com/rappa850/harbor-dl/actions/workflows/docker.yml/badge.svg)](https://github.com/rappa850/harbor-dl/actions/workflows/docker.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

自托管的个人媒体工作台：下载、订阅作者、录制直播，在浏览器里管理和播放自己的媒体库，并能整理成 Jellyfin / Emby 可直接识别的目录。

后端 FastAPI + SQLite，前端 Vue 3 + Vite。项目仍在开发中，已完成和未完成的部分见下文。

## 目录

- [功能](#功能)
- [快速开始（Docker Compose）](#快速开始docker-compose)
- [首次使用](#首次使用)
- [数据与目录](#数据与目录)
- [接入 Jellyfin / Emby](#接入-jellyfin--emby)
- [配置](#配置)
- [升级与备份](#升级与备份)
- [本地开发](#本地开发)
- [测试](#测试)
- [文档](#文档)
- [安全提示](#安全提示)
- [许可](#许可)

## 功能

| 模块 | 能做什么 |
| --- | --- |
| **下载** | 粘贴链接或分享文本，解析元数据与格式（基于 yt-dlp）；队列、取消、重试；字幕与缩略图；全局代理与按平台保存的 Cookie。 |
| **媒体库** | 下载的文件自动入库；类型筛选、搜索、排序；同一作品的图片与音乐合并为一张卡片；封面按常用比例排布，可切换不规则 / 手机 / 平板比例；鼠标悬停静音预览。 |
| **播放器** | 基于 Plyr 的快速预览（倍速、字幕、画中画、快捷键）；类抖音的全屏竖滑沉浸播放；图集轮播 + 背景音乐；断点续播；地址栏记录当前播放，刷新或分享链接可回到原处。 |
| **作者订阅** | 抖音博主：主页或分享链接添加，全量同步（带进度与并发控制）、增量检查、定时检查、新作品自动下载。YouTube 频道 / 歌单、B 站作者支持手动同步与单项下载。 |
| **封面缓存** | 远程封面链接会过期，下载和同步时会把封面按哈希目录缓存到本地。 |
| **媒体服务器导出** | 为每个视频生成「作者 / 标题 [作品ID]」文件夹，里面有视频、封面和标准 NFO，供 Jellyfin / Emby 使用。 |
| **内嵌浏览器登录** | 在专用的 Chrome 用户目录里登录平台并保存 Cookie；Docker 部署通过 noVNC 嵌在页面中。 |
| **直播** | B 站直播间检测、周期监控、TS 录制与录制历史。 |
| **账号与安全** | 首次启动创建管理员；会话登录；可创建 API Token。 |
| **界面** | 统一的设计令牌，浅色 / 深色 / 跟随系统。 |

**还没有做**：直播的录制时段、分段、后处理与其他平台；订阅的其他平台适配、抖音点赞与合集；通知与机器人；AI 助手；Cookie 自动更新；多用户角色。完整清单见 [docs/status.md](docs/status.md)。

## 快速开始（Docker Compose）

需要 Docker 与 Docker Compose。镜像由 GitHub Actions 构建并发布到 GitHub Container Registry，目前只提供 `linux/amd64`。

1. 新建一个目录，保存下面的内容为 `docker-compose.yml`（仓库根目录也有同样的文件）：

   ```yaml
   services:
     harbor-dl:
       image: ghcr.io/rappa850/harbor-dl:latest
       container_name: harbor-dl
       restart: unless-stopped
       ports:
         - "8765:8765"
       shm_size: "1gb"          # 内嵌登录浏览器（Chromium）需要，默认的 64 MB 不够
       environment:
         TZ: Asia/Shanghai
       volumes:
         - ./data:/data         # 数据库、下载、封面缓存、录制、登录浏览器的用户目录
         # - /path/to/media-library:/data/library   # Jellyfin / Emby 的媒体库目录，见下文
   ```

2. 启动：

   ```bash
   docker compose up -d
   ```

3. 打开 `http://localhost:8765`。

常用命令：

```bash
docker compose logs -f        # 查看日志
docker compose pull && docker compose up -d   # 升级到最新镜像
docker compose down           # 停止并删除容器（./data 里的数据保留）
```

> 如果拉取镜像提示没有权限，说明该镜像包还是私有的：在 GitHub 仓库的 Packages 页面把 `harbor-dl` 设为 Public；或者不使用预构建镜像，在源码目录用 `deploy/docker/docker-compose.yml` 本地构建：
> `docker compose -f deploy/docker/docker-compose.yml up -d --build`。

## 首次使用

1. 第一次打开页面时创建管理员账号。
2. **下载**：点右上角「新建下载」，粘贴链接，选择格式。
3. **订阅抖音作者**：进入「作者订阅」，添加作者主页或分享链接。看作品列表需要登录抖音时，在页面里点「登录抖音」，会弹出内嵌浏览器（Docker 下通过 noVNC 显示在页面中）。下载作品本身不需要登录。
4. **媒体库**：下载完成的文件自动出现在「媒体库」，点击封面播放，或使用「沉浸播放」连续观看。

## 数据与目录

容器内的 `/data` 就是数据目录（本地运行时默认是 `./var`）：

| 路径 | 内容 |
| --- | --- |
| `harbor-dl.sqlite3` | 数据库：任务、订阅、设置、播放记录 |
| `downloads/<任务ID>/` | 下载的原始文件 |
| `covers/` | 封面缓存（按哈希分层的目录树） |
| `library/` | 媒体服务器导出目录（默认位置，可在设置中修改） |
| `recordings/` | 直播录制 |
| `browser/` | 登录用的专用浏览器用户目录（含 Cookie） |

备份时至少保存 `harbor-dl.sqlite3` 和 `downloads/`；如果启用了媒体服务器导出，`library/` 里的每个文件夹自带 `.harbor.json`，可以独立备份到网盘。

## 接入 Jellyfin / Emby

1. 打开「设置 → 媒体服务器」，启用导出；需要时修改媒体库目录；勾选「下载完成后自动导出」。
2. 点「导出全部已下载作品」处理已有的作品；单个作品也可以在作品卡片菜单里「导出到媒体库」。
3. 让 Jellyfin / Emby 把这个目录当作媒体库，类型选择「电影」或「家庭视频」。

导出的结构：

```
library/
└── 作者名/
    ├── folder.jpg                      作者头像
    └── 标题 [作品ID]/
        ├── 标题 [作品ID].mp4           与下载文件是同一份（硬链接，跨磁盘时复制）
        ├── 标题 [作品ID].nfo           标准 <movie> NFO
        ├── poster.jpg                  封面
        └── .harbor.json                恢复清单（平台、作品 ID、作者、原始链接）
```

说明：

- 视频、封面、NFO 在同一个文件夹里；封面来自本地缓存，没有缓存时从视频截取一帧。
- 在 Docker 里要让 Jellyfin / Emby 读到这个目录，把它挂载出来：`- /你的媒体库路径:/data/library`，并让 Jellyfin / Emby 的容器挂载同一个路径。
- 在「编辑 NFO」里改过的内容不会被后续自动导出覆盖。
- 图集作品（图片 + 音乐）不导出到媒体服务器目录。
- 设计细节见 [docs/media-server-export.md](docs/media-server-export.md)。

## 配置

大部分设置在页面里完成（下载并发、同步并发、代理、Cookie、媒体库导出）。需要时可以用环境变量调整：

| 环境变量 | 作用 | 默认值 |
| --- | --- | --- |
| `HARBOR_DATA_DIR` | 数据目录 | `./var`（镜像里是 `/data`） |
| `HARBOR_FFMPEG` | FFmpeg 可执行文件路径 | 自动查找系统 `ffmpeg`，找不到时使用 `imageio-ffmpeg` 自带的 |
| `HARBOR_CHROME` | Chrome / Chromium 可执行文件路径 | 自动查找（镜像里是 `/usr/bin/chromium`） |
| `HARBOR_BROWSER_MODE` | `desktop` 弹出可见窗口；`docker` 使用虚拟显示 + noVNC | `desktop`（镜像里是 `docker`） |
| `HARBOR_DISPLAY` | Docker 模式的显示号 | `:99` |
| `HARBOR_NOVNC_DIR` / `HARBOR_VNC_WS` | noVNC 静态目录 / VNC WebSocket 地址 | 镜像内已配置 |
| `TZ` | 时区（Docker） | UTC |

部署细节见 [docs/deployment.md](docs/deployment.md)。

## 升级与备份

```bash
docker compose pull && docker compose up -d
```

数据保存在 `./data`，升级镜像不会影响它。升级前建议复制一份 `./data/harbor-dl.sqlite3`。镜像标签：`latest`（主分支最新）、`1.2.3` / `1.2`（发布版本）、`main`、`sha-xxxxxxx`。

## 本地开发

需要 Python 3.11+、Node.js 22；FFmpeg 用于合并音视频；Chrome 用于内嵌登录和抖音匿名取详情。

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt      # Windows：.venv\Scripts\python.exe
cd frontend && npm install && npm run build && cd ..
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8765
```

前端开发服务器（带热更新，API 代理到 8765 端口）：

```bash
cd frontend && npm run dev
```

## 测试

```bash
python -m unittest discover -s tests          # 后端
cd frontend && node --test tests/*.test.js    # 前端逻辑
```

后端测试不访问真实媒体平台（平台响应使用本地桩），内嵌浏览器相关测试会启动本机 Chrome。推送到 GitHub 后，CI 会自动运行这两组测试并构建前端；Docker 工作流会构建镜像，推送到主分支或打 `v*` 标签时发布。

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/status.md](docs/status.md) | 功能进度与已知限制 |
| [docs/subscriptions.md](docs/subscriptions.md) | 订阅功能与平台适配接口 |
| [docs/browser-login.md](docs/browser-login.md) | 内嵌浏览器登录 |
| [docs/deployment.md](docs/deployment.md) | Docker 部署细节 |
| [docs/media-server-export.md](docs/media-server-export.md) | Jellyfin / Emby 导出设计 |
| [docs/design-system.md](docs/design-system.md) | 界面设计规范 |

## 安全提示

- Cookie 与代理凭据目前**明文**保存在本地数据库中，普通接口不会返回其内容。
- 请勿把服务直接暴露到公网；对外使用请放在带 TLS 的反向代理之后。
- 容器里的 VNC 只监听容器内的 `127.0.0.1`，只能通过已登录的 Harbor-DL 页面访问。
- 抖音等平台的接口依据公开的网页端行为实现，平台改版可能使其失效；请遵守各平台的服务条款，只下载你有权保存的内容。
- 第三方组件的许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 许可

[MIT](LICENSE)。
