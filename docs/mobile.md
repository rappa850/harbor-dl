# 移动端 App（Android）

**定位：辅助。** 项目仍以网页端功能完善为主；移动端只做“刷自己库里的视频”的配套，没有排期，按需再做。

技术栈：Flutter（Android 专属），工程在 `mobile/`。播放用 `video_player`（底层 ExoPlayer），Riverpod 未引入（目前只用 `setState`），网络用 `dio`，token 存 `flutter_secure_storage`。

## 已完成（截至 0.3.0+4，main `9ef67a5`）

- 登录：服务器地址 + 用户名密码换长效 Bearer token（`POST /api/auth/app-login`，365 天，可在网页 API Token 里吊销）。
- 竖滑信息流：3 个播放器的控制器池、封面垫底避免黑屏、后台预取后 2 个视频到磁盘缓存（1 GB LRU）。
- 首页四个标签：推荐（随机，seed 固定翻页不重复）、最新、收藏、历史（历史会从上次位置继续）。
- 互动：心形按钮、双击点赞、长按 2× 快进、进度条（只读）。
- 博主：列表（搜索、三种排序）、详情（头像模糊背景、签名、作品/粉丝/平台、封面网格，点开从该视频起全屏播放）。
- 个人中心：头像与主页背景图可更换/移除、视频/收藏/历史计数、收藏与历史网格、清除缓存、退出登录。
- 底部导航：首页 / 博主 / 我的；切走时首页暂停。
- 手动下载视频的时长（ffprobe，结果记入 `media_probe`，每页最多探测 8 个）、收藏/历史/探测记录在启动时清理已删除媒体、登录失败限流（同地址+用户名 5 次/5 分钟，网页登录与 App 登录共用，0.6.0）。
- 可拖动的进度条、小窗播放按钮（离开 App 时自动进小窗，0.5.0）。
- 离线（0.4.0）：播放页下载按钮保存到手机（含封面），“我的 → 离线”可无网浏览、保存全部收藏、清空；离线副本不受缓存清理影响。
- 省流（0.4.0）：仅 Wi-Fi 预加载（默认开）、缓存上限 512 MB–4 GB 可选。

后端配套：`/api/feed`（游标分页，latest/random/favorites/history，作者过滤）、`/api/files/{id}/poster`（ffmpeg 截帧）、流媒体与封面的缓存头、收藏/历史表、`/api/authors`、`/api/bloggers`、`/api/blogger`、头像/背景图接口（接受 API Token）、`/api/app/me`。

## 未完成

### 体验
- 首页没有隐藏底部导航的沉浸模式。
- 图集作品（图片 + 背景音乐）在 feed 里缺失：需要 feed 返回 `kind=gallery` 并复用 `/api/files/{id}/gallery`，App 做轮播 + 音频。
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
- API Token 没有权限范围，持有即全权限。
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
