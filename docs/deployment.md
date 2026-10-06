# Docker 部署

快速开始见 [README](../README.md#快速开始docker-compose)。本文说明镜像内容与构建方式。

> 验证情况：已在 NAS 上用该镜像实测通过——注册登录、抖音登录并保存、订阅博主、下载、播放与沉浸式播放。另在 Ubuntu 26.04（WSL2，Docker 29，linux/amd64）上验证过构建、启动、重启稳定性和内嵌登录浏览器（`/novnc` 未登录 401、登录后 200）。**未验证**：直播录制（功能未完成）、arm64（不提供）、桥接网络下的端口映射。

## 使用预构建镜像

```bash
docker compose up -d      # 仓库根目录的 docker-compose.yml，镜像 ghcr.io/rappa850/harbor-dl:latest
```

## 本地构建

在仓库根目录：

```bash
docker build -f deploy/docker/Dockerfile -t harbor-dl .
docker run -d --name harbor-dl -p 8765:8765 --shm-size=1g -v $PWD/data:/data harbor-dl
```

或 `docker compose -f deploy/docker/docker-compose.yml up -d --build`。

## 镜像内容

- 多阶段构建：Node 22 构建前端，Python 3.12 (Debian bookworm) 运行后端。
- 运行时包含 Xvfb、fluxbox、x11vnc、noVNC、websockify、Chromium、中文字体（Noto CJK）、FFmpeg 和 tzdata；由 supervisor 管理进程。
- 除 Harbor-DL 外的 VNC 相关进程只监听容器内 `127.0.0.1`，只能通过 Harbor-DL 已鉴权的 `/novnc`、`/websockify` 访问。
- `HEALTHCHECK` 请求 `/api/system/health`。
- supervisor 管理的所有进程输出都写入容器日志，排查启动问题用 `docker logs harbor-dl`。
- `/data` 保存数据库、下载、封面缓存、媒体库导出、录制和专用浏览器用户目录，请挂载持久卷。
- 需要 `shm_size: 1gb`：Chromium 在默认 64 MB 共享内存下容易崩溃。

## GitHub Actions

| 工作流 | 触发 | 作用 |
| --- | --- | --- |
| `.github/workflows/ci.yml` | 推送到 `main`、拉取请求 | 运行后端与前端测试，构建前端（4 个直播录制测试在 Linux 上跳过，见 `tests/test_live_recording.py`） |
| `.github/workflows/docker.yml` | 推送到 `main`、`v*` 标签、相关路径的拉取请求、手动 | 构建镜像（amd64）；拉取请求只构建不推送；其余推送到 `ghcr.io/<owner>/harbor-dl` |

镜像标签：`latest`（主分支）、`main`、`sha-<短哈希>`，以及打 `v1.2.3` 标签时的 `1.2.3` 和 `1.2`。首次推送后，在仓库的 Packages 页面把镜像设为 Public，匿名用户才能拉取。

发布镜像时需要保留各组件的许可证，见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。
