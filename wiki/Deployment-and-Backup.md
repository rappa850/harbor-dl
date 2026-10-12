# Deployment and Backup

快速开始见 [[Quick Start]]。本文说明镜像内容、数据目录、反向代理、升级与备份。

## 镜像内容

- 多阶段构建：Node 22 构建前端，Python 3.12 (Debian bookworm) 运行后端；
- 运行时包含 Xvfb、fluxbox、x11vnc、noVNC、websockify、Chromium、中文字体（Noto CJK）、FFmpeg 和 tzdata，由 supervisor 管理进程；
- `HEALTHCHECK` 请求 `/api/system/health`；
- 所有进程输出都写入容器日志，排查启动问题用 `docker logs harbor-dl`；
- 需要 `shm_size: 1gb`：Chromium 在默认 64 MB 共享内存下容易崩溃；
- 目前只提供 `linux/amd64`。

## 本地构建镜像

```bash
docker build -f deploy/docker/Dockerfile -t harbor-dl .
docker run -d --name harbor-dl -p 8765:8765 --shm-size=1g -v $PWD/data:/data harbor-dl
```

或 `docker compose -f deploy/docker/docker-compose.yml up -d --build`。

## 数据目录

容器内的 `/data`（本地运行时默认 `./var`）：

| 路径 | 内容 |
| --- | --- |
| `harbor-dl.sqlite3` | 数据库：任务、订阅、设置、播放记录 |
| `downloads/<任务ID>/` | 下载的原始文件 |
| `covers/` | 封面缓存（按哈希分层的目录树） |
| `library/` | 媒体服务器导出目录（默认位置，可在设置中修改） |
| `recordings/` | 直播录制 |
| `browser/` | 登录用的专用浏览器用户目录（含 Cookie） |

请把 `/data` 挂载为持久卷。

## 反向代理（TLS）

不要把 8765 端口直接暴露到公网。放在带 TLS 的反向代理后面，并确保代理转发 WebSocket（内嵌登录浏览器的 `/websockify` 需要）。Caddy 示例：

```
harbor.example.com {
    reverse_proxy localhost:8765
}
```

Nginx 需要为 WebSocket 加上 `Upgrade` / `Connection` 头。

## 升级

```bash
docker compose pull && docker compose up -d
```

数据保存在 `./data`，升级镜像不会影响它。升级前建议复制一份 `./data/harbor-dl.sqlite3`。

镜像标签：`latest`（主分支最新）、`1.2.3` / `1.2`（发布版本）、`main`、`sha-xxxxxxx`。

## 备份

- 至少保存 `harbor-dl.sqlite3` 和 `downloads/`；
- 启用了媒体服务器导出时，`library/` 里的每个文件夹自带 `.harbor.json`，可以独立备份到网盘（见 [[Media Server Export]]）；
- 订阅可以在「作者订阅 → 导入 / 导出」里单独导出清单。

## GitHub Actions

| 工作流 | 触发 | 作用 |
| --- | --- | --- |
| `ci.yml` | 推送到 `main`、拉取请求 | 运行后端与前端测试，构建前端 |
| `docker.yml` | 推送到 `main`、`v*` 标签、相关路径的拉取请求、手动 | 构建镜像（amd64）；拉取请求只构建不推送；其余推送到 `ghcr.io/<owner>/harbor-dl` |

首次推送后，在仓库的 Packages 页面把镜像设为 Public，匿名用户才能拉取。

## 验证情况

已在 NAS 上用该镜像实测通过：注册登录、抖音登录并保存、订阅博主、下载、播放与沉浸式播放。**未验证**：直播录制（功能未完成）、arm64（不提供）、桥接网络下的端口映射。
