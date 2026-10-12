# Browser Login

用于登录平台并保存 Cookie（目前启用抖音）。浏览器是一个共享的 Chrome，使用专用用户目录 `<数据目录>/browser/chrome-profile`，**不使用也不触碰你日常 Chrome 的配置**；登录状态保留在该目录里。

## 两种模式

| 模式 | 适用 | 行为 |
| --- | --- | --- |
| 桌面模式（默认） | 在自己电脑上本地运行 | 弹出一个普通的可见 Chrome 窗口，登录后回到页面点「保存登录状态」 |
| Docker 模式（`HARBOR_BROWSER_MODE=docker`，镜像里默认） | NAS / 服务器 | Chrome 运行在虚拟显示（Xvfb），页面弹窗里通过 noVNC 内嵌显示 |

## 使用

1. 在「作者订阅 → 添加订阅」里点「登录抖音」，或在 [[Settings and Configuration]] 里操作。
2. 在弹出的浏览器里完成登录。
3. 点「保存登录状态」。只有包含登录标志 Cookie（抖音：`sessionid` / `sessionid_ss`）才允许保存。
4. 登录过期时，订阅页会提示「需要重新登录」，重复以上步骤即可。

## 行为说明

- Docker 模式下页面每 10 秒发送心跳，超过 600 秒无心跳自动关闭；有订阅同步 / 检查在运行时不关。
- 用户直接关闭窗口会如实显示为未运行；服务停止时自动关闭浏览器。
- 保存后接口响应中不含 Cookie 内容。

## 安全说明

- `/novnc/*` 与 WebSocket `/websockify` 由 Harbor-DL 自己转发，需要登录会话且校验同源；VNC 相关进程只监听容器内 `127.0.0.1`。
- Chrome 的调试端口只绑定 `127.0.0.1`，但浏览器运行期间同机其他进程可以连它读取 Cookie；浏览器只在登录期间运行。
- Cookie 仍**明文**保存在本地数据库中。

## 排查

- 找不到 Chrome：设置 `HARBOR_CHROME` 指向 Chrome / Chromium 可执行文件。
- Docker 下浏览器崩溃：确认 `shm_size: "1gb"`。
