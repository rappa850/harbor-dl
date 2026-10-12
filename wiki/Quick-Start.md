# Quick Start

用 Docker Compose 部署是最省事的方式。镜像由 GitHub Actions 构建并发布到 GitHub Container Registry，目前只提供 `linux/amd64`。

## 前提

- 已安装 Docker 与 Docker Compose
- 一个用来保存数据的目录（下面用 `./data`）

## 步骤

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
         # - /path/to/media-library:/data/library   # Jellyfin / Emby 的媒体库目录
   ```

2. 启动：

   ```bash
   docker compose up -d
   ```

3. 打开 `http://localhost:8765`，进入 [[First Steps]]。

## 常用命令

```bash
docker compose logs -f                        # 查看日志
docker compose pull && docker compose up -d   # 升级到最新镜像
docker compose down                           # 停止并删除容器（./data 里的数据保留）
```

## 拉取镜像提示没有权限

说明该镜像包还是私有的。二选一：

- 在 GitHub 仓库的 **Packages** 页面把 `harbor-dl` 设为 Public；
- 不使用预构建镜像，在源码目录本地构建：

  ```bash
  docker compose -f deploy/docker/docker-compose.yml up -d --build
  ```

## 不用 Docker

见 [[Development]]：需要 Python 3.11+、Node.js 22、FFmpeg；内嵌登录和抖音匿名取详情还需要 Chrome。

## 安全提醒

请勿把服务直接暴露到公网；对外使用请放在带 TLS 的反向代理之后，详见 [[Deployment and Backup]]。
