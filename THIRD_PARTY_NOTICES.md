# 第三方组件

Harbor-DL 的代码使用 MIT 许可；第三方依赖和外部程序保留各自的许可证，不由本项目重新授权。

## 随源码分发

- `backend/vendor/douyin_ab_sign.py`：复制自 streamget 4.0.9（https://github.com/ihmily/streamget，包元数据标注 MIT，版权 Hmily）的纯 Python `a_bogus` 签名实现，文件头保留出处。该发行包未附带许可证正文，发布前须从上游仓库核对并补入完整 MIT 文本。

## Python 依赖

FastAPI、Uvicorn、httpx、yt-dlp、websockets（BSD-3-Clause）、imageio-ffmpeg（BSD-2-Clause，随包附带 FFmpeg）。手动录制优先使用系统 FFmpeg，缺省使用 imageio-ffmpeg 附带的程序；Windows 版附带的 FFmpeg 为 gyan.dev 构建，启用了 GPL / version3，因此该二进制不能标注为 MIT。发布安装包或容器时须分别保留实际所用 FFmpeg 的许可证与发行信息。

## 前端

Vue、Vite 及其构建依赖，见 `frontend/package.json`，各自适用其许可证。

## 外部程序（通过子进程调用，不随源码分发）

Google Chrome / Chromium（内嵌登录与匿名取数）、FFmpeg / FFprobe；Docker 镜像另含 Xvfb、fluxbox、x11vnc、noVNC、websockify、supervisor 等系统包。

完整的依赖清单与 SBOM 尚未生成。
