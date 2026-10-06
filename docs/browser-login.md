# 内嵌浏览器登录

用于登录平台并保存 Cookie（目前启用抖音）。浏览器是一个共享的 Chrome，使用专用用户目录 `<数据目录>/browser/chrome-profile`，**不使用也不触碰你日常 Chrome 的配置**；登录状态保留在该目录里。

## 两种模式

- **桌面模式（默认）**：弹出一个普通的可见 Chrome 窗口，登录后回到页面点“保存登录状态”。
- **Docker 模式**（`HARBOR_BROWSER_MODE=docker`）：Chrome 运行在虚拟显示（Xvfb），页面弹窗里通过 noVNC 内嵌显示。`/novnc/*` 与 WebSocket `/websockify` 由 Harbor-DL 自己转发，需要登录会话且校验同源；VNC 相关进程只监听 127.0.0.1。

## 行为

- Chrome 由 `HARBOR_CHROME` 或常见安装路径定位；找不到会明确提示。
- 通过 Chrome DevTools 协议（随机端口，仅 127.0.0.1）读取 Cookie，只取平台自己域名下的；必须包含登录标志 Cookie（抖音：`sessionid` / `sessionid_ss`）才允许保存。无法写入请求头的 Cookie（空名字等）会被跳过。保存后响应中不含 Cookie 内容。
- 每次启动前清理 Chrome 遗留的单例锁文件；用户直接关闭窗口会如实显示为未运行；服务停止时关闭浏览器。
- Docker 模式下页面每 10 秒发送心跳，超过 600 秒无心跳自动关闭，但有订阅同步 / 检查在运行时不关。
- 平台表 `backend/browser_login.py: PLATFORMS`：新增平台只需添加登录页、域名和登录标志 Cookie，并在 `network.PLATFORMS` 里有同名 Cookie 槽。

## 接口

`GET /api/browser`、`POST /api/browser/{platform}/login`、`POST /api/browser/heartbeat`、`POST /api/browser/{platform}/save`、`POST /api/browser/close`。

## 安全说明

调试端口只绑定 127.0.0.1，但浏览器运行期间同机其他进程可连接它读取 Cookie；浏览器只在登录期间运行。Cookie 仍明文保存在本地数据库中。

## 匿名取数

`backend/browser_fetch.py` 提供一次性的匿名无头 Chrome（临时用户目录、无登录），用于让页面自带的脚本给请求签名后再取数；抖音下载使用它。
