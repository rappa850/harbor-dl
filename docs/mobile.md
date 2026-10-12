# 移动端 App（Android）

> 把 App 做成“远程控制台”的计划见 [mobile-roadmap.md](mobile-roadmap.md)。

**定位：辅助。** 项目仍以网页端功能完善为主；移动端只做“刷自己库里的视频”的配套，没有排期，按需再做。

技术栈：Flutter（Android 专属），工程在 `mobile/`。播放用 `video_player`（底层 ExoPlayer），Riverpod 未引入（目前只用 `setState`），网络用 `dio`，token 存 `flutter_secure_storage`。

## 已完成（截至 0.3.0+4，main `9ef67a5`）

- 登录：服务器地址 + 用户名密码换长效 Bearer token（`POST /api/auth/app-login`，365 天，可在网页 API Token 里吊销）。
- 竖滑信息流：3 个播放器的控制器池、封面垫底避免黑屏、后台预取后 2 个视频到磁盘缓存（1 GB LRU）。
- 首页四个标签：推荐（随机，seed 固定翻页不重复）、最新、收藏、历史（历史会从上次位置继续）。
- 互动：心形按钮、双击点赞、长按 2× 快进、进度条（只读）。
- 博主：列表（搜索、三种排序）、详情（头像模糊背景、签名、作品/粉丝/平台、封面网格，点开从该视频起全屏播放）。
- 个人中心：头像与主页背景图可更换/移除、视频/收藏/历史计数、收藏与历史网格、清除缓存、退出登录。
- 底部导航：首页 / 博主 / 订阅 / 下载 / 我的（0.8.0 起）；切走时首页暂停。
- 手动下载视频的时长（ffprobe，结果记入 `media_probe`，每页最多探测 8 个）、收藏/历史/探测记录在启动时清理已删除媒体、登录失败限流（同地址+用户名 5 次/5 分钟，网页登录与 App 登录共用，0.6.0）。
- 0.7.0：播放页右侧增加“自动连播 / 单曲循环”切换（默认自动连播，记住选择）；播放时屏幕常亮；首页切换标签不再闪现“没有视频”提示；博主列表与详情包含已同步但未下载的作品（只展示和请求下载，不会进入播放区）。
- 0.8.0（控制台）：底部导航变为 首页 / 博主 / 订阅 / 下载 / 我的。App 登录改为申请 `manage` 权限。
  - **订阅**：列表（类型、作品数、检查状态、需要重新登录 / 检查失败提示）；订阅详情：检查更新、全量同步（轮询进度，可离开页面）、下载全部未下载、分批下载（最新 20 / 50 / 100）、作品按状态筛选并分页、长按多选后下载或移除记录、点单个作品下载 / 播放、清理文件缺失的记录、订阅设置（昵称、检查频率、画质、自动下载、NFO）、删除订阅；添加订阅支持抖音博主 / 我的点赞 / 我的收藏 / 合集（可从“我收藏的合集”里选）、YouTube 频道 / 歌单、B 站作者。
  - **下载**：任务队列（进行中 / 已完成 / 失败筛选，进度与速度，取消 / 重试 / 删除，可选是否同时删文件）；粘贴链接或分享文本 → 解析 → 选画质 → 下载。
  - **我的 → 设置 → 服务器状态与日志**：版本与 FFmpeg、队列计数、磁盘、并发数（可改）、各平台登录是否已保存、最近的失败记录。
  - 0.9.0：**直播**（订阅页右上角）：直播订阅列表、检测是否开播、开始 / 停止录制、周期监控与开播自动录制开关、录制记录；**图集**：订阅里已下载的图集作品点开后可左右滑动看图（可缩放），背景音乐自动播放、可静音。
  - 仍只能在网页端做：登录平台（内嵌浏览器）、改密码、管理 API Token（这些接口只接受浏览器会话）。
- 可拖动的进度条、小窗播放按钮（离开 App 时自动进小窗，0.5.0）。
- 离线（0.4.0）：播放页下载按钮保存到手机（含封面），“我的 → 离线”可无网浏览、保存全部收藏、清空；离线副本不受缓存清理影响。
- 省流（0.4.0）：仅 Wi-Fi 预加载（默认开）、缓存上限 512 MB–4 GB 可选。

后端配套：`/api/feed`（游标分页，latest/random/favorites/history，作者过滤）、`/api/files/{id}/poster`（ffmpeg 截帧）、流媒体与封面的缓存头、收藏/历史表、`/api/authors`、`/api/bloggers`、`/api/blogger`、头像/背景图接口（接受 API Token）、`/api/app/me`。

## 未完成

### 体验
- 首页没有隐藏底部导航的沉浸模式。
- 图集作品（图片 + 背景音乐）在首页 feed 里仍缺失（订阅作品列表里可以看）：需要 feed 返回 `kind=gallery` 并复用 `/api/files/{id}/gallery`。
- 没有通知（下载完成 / 新作品 / 开播）：服务端还没有通知通道。
- 没有接收系统分享菜单里的链接（需要 Android intent 原生配置）；下载页可以手动粘贴。
- 博主头像要下拉刷新一次才出现（后端是后台下载，列表已支持下拉刷新）。
- 作者页没有作者列表入口之外的筛选（如按平台）。

### 打磨与发布（P4 余项）
- 小窗播放（画中画）未在真机上验证；后台只出声（无画面）的播放没有做。
- 真机帧时间与首帧耗时的性能调优（目标 p95 < 16 ms）。
- release 签名密钥还没生成：目前 `flutter build apk --release` 回退用 debug 密钥签名（和已装的 debug 包签名一致，可覆盖安装）。换成正式密钥后必须先卸载旧包。
- 应用图标是自绘的矢量自适应图标（Android 8+），旧系统仍是 Flutter 默认图标。
- CI 新增了 `mobile` 任务（analyze + test），还没在 GitHub 上跑过。

### 安全与部署
- 目前只面向局域网：明文 HTTP 全放行（`usesCleartextTraffic`）。上公网需要 HTTPS 反代，并收紧为只对内网放行。
- API Token 有三档权限范围（`read` 浏览播放与个人状态、`download` 另可创建下载与检查 / 同步订阅、`manage` 全部），规则见 `backend/token_scopes.py`。`app-login` 默认签发 `download`，可用 `scope` 字段申请其他档位；升级前已有的 Token 视为 `manage`。浏览器会话不受限制。
- 博主按作者名区分，不同平台的同名博主会合并。

## 构建与安装

```bash
cd mobile
flutter analyze && flutter test
flutter build apk --debug      # 产物：build/app/outputs/flutter-apk/app-debug.apk
```

- Flutter 装在 `C:\Users\84422\dev\flutter`；国内网络需要镜像：`PUB_HOSTED_URL=https://pub.flutter-io.cn`、`FLUTTER_STORAGE_BASE_URL=https://storage.flutter-io.cn`（已写入用户环境变量）。
- release 包约 53 MB（debug 约 174 MB）：`flutter build apk --release`。正式签名：在 `mobile/android/key.properties` 写 `storeFile/storePassword/keyAlias/keyPassword`（已 git 忽略），密钥丢失则无法覆盖升级。
- 每次发新包都要提高 `pubspec.yaml` 的版本号（`version: x.y.z+N`），否则部分系统（HyperOS/MIUI）会静默忽略覆盖安装。
- 侧载用的包放 `mobile/dist/`（已在 `.gitignore`），文件名带版本号，避免装到旧文件。
- 后端要让手机访问：`uvicorn backend.app:app --host 0.0.0.0 --port 8765`，并放行 Windows 防火墙入站 8765。
