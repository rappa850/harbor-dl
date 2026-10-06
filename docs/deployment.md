# Docker 部署

快速开始见 [README](../README.md#快速开始docker-compose)。本文说明镜像内容与构建方式。

> 已在 Ubuntu 26.04（WSL2，Docker 29，linux/amd64）上构建并运行验证：镜像可构建；容器启动后健康检查通过，前端与深链接可访问，连续重启 3 次稳定；创建管理员后可启动内嵌登录浏览器（Chromium 在虚拟显示里运行），`/novnc` 未登录返回 401、登录后返回 200。**未验证**：arm64 镜像、真实的抖音登录流程、桥接网络下的端口映射。

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
| `.github/workflows/ci.yml` | 推送到 `main`、拉取请求 | 运行后端与前端测试，构建前端 |
| `.github/workflows/docker.yml` | 推送到 `main`、`v*` 标签、相关路径的拉取请求、手动 | 构建镜像；拉取请求只构建（amd64）不推送；其余推送到 `ghcr.io/<owner>/harbor-dl`（amd64 + arm64） |

镜像标签：`latest`（主分支）、`main`、`sha-<短哈希>`，以及打 `v1.2.3` 标签时的 `1.2.3` 和 `1.2`。首次推送后，在仓库的 Packages 页面把镜像设为 Public，匿名用户才能拉取。

发布镜像时需要保留各组件的许可证，见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。
