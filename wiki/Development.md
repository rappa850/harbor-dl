# Development

## 环境

- Python 3.11+
- Node.js 22
- FFmpeg（合并音视频）
- Chrome / Chromium（内嵌登录和抖音匿名取详情）

## 启动

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt      # Windows：.venv\Scripts\python.exe
cd frontend && npm install && npm run build && cd ..
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8765
```

数据默认放在 `./var`，可用 `HARBOR_DATA_DIR` 修改。

前端开发服务器（热更新，API 代理到 8765 端口）：

```bash
cd frontend && npm run dev
```

## 测试

```bash
python -m unittest discover -s tests          # 后端
cd frontend && node --test tests/*.test.js    # 前端逻辑
```

后端测试不访问真实媒体平台（平台响应使用本地桩），内嵌浏览器相关测试会启动本机 Chrome。推送到 GitHub 后 CI 会自动运行这两组测试并构建前端。

## 代码结构

| 路径 | 内容 |
| --- | --- |
| `backend/` | FastAPI 应用（`app.py`）、下载、订阅、媒体库导出、直播、浏览器登录等模块 |
| `backend/subscription_platforms/` | 订阅平台适配器：继承 `SubscriptionAdapter` 并在 `default_registry()` 注册即可新增平台 |
| `frontend/` | Vue 3 + Vite 前端，路由是自带的极简历史路由（`src/router.js`） |
| `mobile/` | Flutter Android App |
| `deploy/docker/` | Dockerfile 与本地构建用的 compose 文件 |
| `docs/` | 设计与现状文档 |
| `tests/` | 后端测试 |

## 文档

仓库 `docs/` 里有更细的设计文档：`status.md`、`subscriptions.md`、`browser-login.md`、`deployment.md`、`media-server-export.md`、`design-system.md`、`mobile.md`、`mobile-roadmap.md`。

## 许可

MIT。发布镜像时需要保留各组件的许可证，见 `THIRD_PARTY_NOTICES.md`。
