# Docker 部署

> 这些文件在当前版本里**尚未在容器中构建验证**，首次构建可能需要调整。

在项目根目录构建并运行：

```bash
docker build -f deploy/docker/Dockerfile -t harbor-dl .
docker run -d --name harbor-dl -p 8765:8765 --shm-size=1g -v $PWD/data:/data harbor-dl
```

或使用 `deploy/docker/docker-compose.yml`。

- 镜像包含前端构建、Python 依赖、Xvfb、fluxbox、x11vnc、noVNC、websockify、Chromium、中文字体和 FFmpeg；supervisor 管理进程。
- 除 Harbor-DL 外的 VNC 进程只监听容器内 127.0.0.1，只能通过 Harbor-DL 已鉴权的 `/novnc`、`/websockify` 访问。
- `/data` 保存数据库、下载、录制和专用浏览器用户目录，请挂载持久卷。
- 对外使用时请放在带 TLS 的反向代理之后。
- 镜像使用 Debian 的 Chromium；发布镜像时需要保留各组件的许可证。
