# 开发计划：抖音点赞 / 收藏 / 合集 + 手机端完整控制台 + 体验收尾

三条线并行规划，但按依赖顺序实施。每个阶段一个 feat 分支，带后端测试（有新接口时）和 Flutter 测试，合并前文档同步（`docs/subscriptions.md`、`docs/status.md`、`docs/mobile-roadmap.md`）。

## 现状要点（决定了计划形状）

- 订阅身份目前只有"博主"：`SubscriptionConfig.subscription_type` 已有字段，但 `DouyinAdapter.describe_unavailable` 对非 `user` 直接返回"尚未适配"；`subscription_profiles.ProfileInput` 对抖音只接受主页链接。
- 适配器接口（`resolve` / `fetch` / `download_target`）已经够用，点赞、收藏、合集只需新增"来源类型"，不必改接口。
- 订阅表按 `identity` 唯一，需要让点赞 / 收藏 / 合集有不同的 identity（见阶段 2）。
- 手机端 0.7.0 只有播放 / 博主 / 收藏 / 离线，没有任何写操作；服务端订阅、任务、同步接口基本齐全（见 `docs/mobile-roadmap.md` 第一节）。
- 服务启动时，未完成的下载一律标 `ERROR`（`backend/downloads.py` `start()`），需要手动重试。

## 阶段 0：体验收尾（小改动，先做，独立合并）

| # | 内容 | 做法 | 验收 |
| --- | --- | --- | --- |
| 0.1 | 重启后自动恢复下载 | `start()` 里把 `DOWNLOADING` / `PROCESSING` 改回 `QUEUED`（保留一次 `RESUMED` 事件），记录 `retries` 计数，超过 3 次再标 `ERROR`，避免反复崩溃的任务无限重启；清掉残留的 `.part` 或让下载器覆盖续传 | 测试：模拟中断任务，重启后进入队列；超过上限则 `ERROR` |
| 0.2 | Cookie 过期可见 | 抖音请求遇到登录失效特征（`status_code` 非 0 且为登录类、或 `UIFID` 缺失）时在订阅上记录 `auth_expired` 状态；订阅列表 / 详情、手机端、设置页显示"需要重新登录抖音"，并给"去登录"入口 | 测试：模拟登录失效响应，订阅 `runtime` 带 `auth_expired`；检查后不再无限重试 |
| 0.3 | 检查漏更新提示 | 增量检查读满页数上限仍全是新作品时，在状态里标"可能有更多新作品，建议全量同步"，不静默丢 | 测试：构造整页新作品，状态带该提示 |
| 0.4 | 图集 NFO 与导出 | 图集生成 NFO，导出到 Jellyfin / Emby 目录时第一张图作封面、其余图片放入文件夹、背景音乐一并放入；更新 `docs/media-server-export.md` | 测试：`test_library_export.py` 新增图集用例 |
| 0.5 | 文档修正 | `docs/status.md` 已知限制去掉已解决项 | — |

## 阶段 1：服务端 — 令牌权限范围（手机端写操作的前提）

`mobile-roadmap.md` 第三节第 1 点要求：App 能删文件、改订阅之前先做。

- API Token 增加 `scope`：`read`（播放 / 查看）、`download`（创建任务、同步、下载）、`manage`（增删改订阅、删除记录、清理、设置）。
- 路由按动词和资源映射所需 scope，缺失返回 403 并说明所需范围；旧 Token 迁移为 `manage`，避免升级后失效。
- App 登录时申请的 Token 用 `manage`；设置页可见各 Token 的范围。
- 测试：每类接口各一组"范围不够被拒绝 / 足够通过"。

## 阶段 2：抖音点赞 / 收藏 / 合集

### 2.1 数据模型与身份

| 类型 | `subscription_type` | identity | 需要登录 |
| --- | --- | --- | --- |
| 博主作品（已有） | `user` | `douyin:user:{sec_uid}` | 是（读取） |
| 我的点赞 | `likes` | `douyin:likes:{本人 sec_uid}` | 是（本人） |
| 我的收藏 | `collection` | `douyin:collection:{本人 sec_uid}` | 是（本人） |
| 合集 | `mix` | `douyin:mix:{mix_id}` | 是 |

- 点赞 / 收藏属于**登录账号本人**，不是任意博主：添加时不要求链接，从当前 Cookie 取本人资料（`/aweme/v1/web/user/profile/self/`），没有 Cookie 就提示先登录。
- 别人的点赞列表往往未公开，不做；合集用合集链接或作品页的合集入口解析 `mix_id`。
- 迁移：现有行 `subscription_type` 缺省视为 `user`；`describe_unavailable` 按类型分别校验必需字段。

### 2.2 适配器

在 `backend/subscription_platforms/douyin.py` 内按类型分发（文件变大后拆出 `douyin_sources.py`，不拆分接口）：

- 点赞：`/aweme/v1/web/aweme/favorite/`，游标 `max_cursor`，字段与作品一致，复用 `entry_from_aweme`。
- 收藏：`/aweme/v1/web/aweme/listcollection/`（POST，`cursor` 分页），同样复用解析。
- 合集：`/aweme/v1/web/mix/aweme/`（`mix_id` + `cursor`），合集资料取名称和作品数；另提供"我收藏的合集"列表用于选择添加。
- 其余沿用：`a_bogus` 签名、重试、错误上报（空响应不当成"没有作品"）。
- **接口细节需先抓包核实**：以上路径与参数来自网页端行为的公开资料，实施第一步是用内嵌浏览器抓取真实请求，写成 fixture 再写适配器；抓不到或参数变化时以 fixture 为准，不凭记忆。
- 增量检查：点赞和收藏按"最新在前"，沿用"整页已知即停"；合集可能按时间正序，需在 fixture 里确认排序，必要时合集走"读到底再比对"。
- 下载沿用 `download_target`（匿名无头 Chrome，不用登录 Cookie），无需改动。

### 2.3 API 与网页端

- `POST /api/subscriptions` 的 `ProfileInput` 增加 `source: user | likes | collection | mix`（默认 `user`），`mix` 需要合集链接或 `mix_id`。
- 新增 `GET /api/douyin/collections`：列出登录账号收藏的合集，供添加时选择。
- 订阅页添加对话框：新增"来源"切换；列表里点赞 / 收藏 / 合集订阅用不同图标和标签；作品作者字段用作品原作者，媒体库按原作者归类的规则要确认（点赞和收藏的作品作者不是订阅所有者）。
- 点赞 / 收藏默认**不自动下载**（量可能很大），添加时明确提示并提供"仅同步列表"。
- 测试：新增 `test_subscription_douyin_sources.py`，用 fixture + mock transport 覆盖三种来源的分页、增量、登录失效、未公开。

### 2.4 风险

- 点赞 / 收藏接口风控比博主作品更严，保留重试与间隔；全量同步可能很长，沿用进度与可取消。
- 点赞列表被用户设为私密时，接口会返回空或错误码，需要报成平台错误而不是"无作品"。

## 阶段 3：手机端完整控制台（按 `mobile-roadmap.md`，在此细化）

底部导航改为：首页 / 博主 / 订阅 / 下载 / 我的。

| 子阶段 | 内容 | 所用服务端接口 | 需要新增 |
| --- | --- | --- | --- |
| 3A 订阅控制台 | 订阅列表（昵称、类型、上次检查、已下载 / 未下载、同步状态、需重新登录标记）；每个订阅：立即同步、全量同步（轮询 `sync-progress`）、全量下载、分批下载（20 / 50 / 100）、重试失败、清理丢失、移除记录；订阅详情作品网格（状态角标、筛选、多选）；订阅设置（间隔、自动下载、画质、NFO）；添加订阅（博主 / 点赞 / 收藏 / 合集） | 现有 `check` / `sync` / `videos` / `videos/download` / `orphan/cleanup` / `PATCH` | `videos/download` 增加 `limit` 参数（"下一批 N 个"），同步结果返回新增数量 |
| 3B 下载队列 | 任务列表（排队 / 下载中 / 完成 / 失败）、进度、取消 / 重试 / 删除；粘贴链接 → 解析 → 选画质 → 下载；接收系统分享（Android intent） | `/api/tasks`、`/api/media/parse`、`/api/dashboard` | 无（3–5 秒轮询） |
| 3C 图集与文件库 | feed 增加 `kind=gallery`，轮播 + 背景音乐；文件库列表、删除、导出到媒体库 | `/api/files`、`/api/library/export` | `/api/feed` 返回图集类型 |
| 3D 系统与账号 | 服务健康、磁盘、并发数；Cookie 状态与过期提示（登录只能在网页端，提示去登录）；Token 管理、改密码、退出其他设备；日志查看 | `/api/system/health`、`/api/network`、`/api/logs`、Token 接口 | 无 |
| 3E 直播与通知 | 直播订阅、开播、录制记录；通知通道 | `/api/live/...` | 通知通道（服务端尚未有），放最后 |

约定：
- 所有长操作以服务端状态为准，App 只轮询展示，退出再进入仍可见进度。
- 高危操作（删除、清理、全量下载）二次确认；批量下载显示队列位置，避免反复点。
- 每个子阶段递增版本号（`pubspec.yaml`）并更新 `docs/mobile.md`。

## 实施顺序

1. **阶段 0** 体验收尾（可立即开始，1–2 个 PR）。
2. **阶段 1** Token 权限范围。
3. **阶段 2** 抖音点赞 / 收藏 / 合集（先抓包出 fixture，再写适配器，再接前端）。
4. **阶段 3A** 手机端订阅控制台；添加订阅时同步支持阶段 2 的新来源。
5. **3B → 3C → 3D**，最后 **3E**。

阶段 2 与 3A 可并行（服务端和 Flutter 互不阻塞），但 3A 的"添加点赞 / 收藏 / 合集"入口要等阶段 2 的接口稳定后接上。

## 已确定的决定

1. **点赞 / 收藏作品的归属**：作品既属于“我的点赞 / 我的收藏”订阅（在该订阅的作品列表里可见、可筛选、可播放），也要在之后订阅原作者时被识别为已有。实现方式：同一平台的作品按 `video_id` 跨订阅去重——任一订阅里已下载的作品，在其他订阅里首次出现时直接关联到同一份文件（状态为已下载，不再入队、不重复下载），反向同理；文件按**原作者**归类到媒体库目录，不另建“我的点赞”目录。
2. **默认不自动下载**：点赞、收藏订阅添加时 `auto_download=false`（合集沿用普通默认，由用户在添加对话框里选择）。
3. **Token 权限**：`read` / `download` / `manage` 三档。
4. **风控**：点赞 / 收藏接口的请求间隔、重试和失败提示由实现阶段先行处理（更长的翻页间隔、单次读取页数上限、风控与登录失效分开报告），真机验证由你后续进行。

## 进度

- [x] 阶段 0：体验收尾（重启自动恢复下载、Cookie 失效提示、漏更新提示、图集 NFO 与导出）
- [x] 阶段 1：Token 权限范围
- [x] 阶段 2：抖音点赞 / 收藏 / 合集（含跨订阅去重；接口待真机验证）
- [ ] 阶段 3：手机端控制台——3A 订阅控制台、3B 下载队列、3D 系统状态已完成（0.8.0）；3C 图集与文件库、3E 直播与通知未做
