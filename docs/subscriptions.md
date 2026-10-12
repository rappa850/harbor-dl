# 作者订阅

## 平台适配接口

`backend/subscription_platforms/` 定义 `SubscriptionAdapter`：身份解析 `resolve`、分页读取作品 `fetch`、下载计划 `download_target`、可下载性 `downloadable`、不受支持原因 `describe_unavailable`，由 `AdapterRegistry` 按平台分发。没有适配器的平台（YouTube、B 站）走通用的 yt-dlp 路径。新增平台：继承适配器并在 `default_registry()` 注册。适配器声明的平台若类型不受支持（如抖音点赞 / 合集），接口会明确返回原因。

## 抖音博主

- **添加**：博主主页链接（`douyin.com/user/{sec_uid}`）或分享文本里的 `v.douyin.com` 短链接。作品链接会被拒绝。保存昵称、签名、头像、粉丝 / 获赞 / 作品数。昵称留空用平台昵称，填写则锁定。
- **读取作品**需要登录 Cookie（用[内嵌浏览器登录](browser-login.md)获得），请求带 `a_bogus` 签名（`backend/vendor/douyin_ab_sign.py`，来源见 THIRD_PARTY_NOTICES）。平台偶发的 403 / 空响应会换新签名重试最多 3 次。空响应、HTTP 错误或错误码都按平台错误报告，不会当成“没有作品”。
- **同步与检查**：
  - 手动全量同步按游标读取到平台结束，失败时已保存的作品不变。
  - 增量检查：无作品记录时最多读 3 页，之后最多 5 页，读到一页全是已知作品（置顶作品不计）就停止。
  - 后台调度每 60 秒扫描一次，到期的订阅串行检查，之间随机停 3–8 秒；失败后等一个检查间隔再试。同一订阅的同步与检查互斥。
  - 新作品按“自动下载”开关加入下载队列（视频和图集都下载）。
  - 增量检查读满页数上限时仍全是新作品，会提示“可能还有更多新作品”（`runtime.more_available`），全量同步成功后清除。
  - 登录失效（平台返回登录类错误码、缺少 UIFID，或未保存 Cookie 时空响应）会标记 `runtime.auth_expired`，订阅页显示“需要重新登录”；下一次成功的检查或同步会清除。已保存 Cookie 时的空响应仍按风控处理，不算登录失效。
- **下载（不需要登录）**：任务开始时才取作品详情，**不使用已保存的登录 Cookie**，只用代理。做法是用一次性匿名无头 Chrome（临时用户目录，用后删除）打开作品页，等页面自带签名脚本就绪后在页面里请求详情接口。
  - 视频：取最高码率，去掉水印路径；音乐轨不会被当成视频。
  - 图集：下载全部图片（多为 webp）和背景音乐（`_bgm.mp3`，失败不影响图片），第一张图为主文件；任何一张图被拦截则任务失败。

## 抖音点赞 / 收藏 / 合集

`POST /api/subscriptions` 的 `source` 字段选择来源（默认 `user`）：

| `source` | `subscription_type` | 说明 | 链接 |
| --- | --- | --- | --- |
| `user` | `user` | 博主作品（见上） | 主页链接 / 短链接 |
| `like` | `like` | **当前登录账号**点赞过的作品 | 不需要，从已保存的 Cookie 取本人资料 |
| `favorite` | `favorite` | **当前登录账号**收藏的作品 | 不需要 |
| `mix` | `mix` | 一个合集（`collection_id` 为合集 ID） | 合集链接（`/collection/{id}`）、`v.douyin.com` 短链接或纯数字 ID |

- 点赞和收藏属于登录账号本人，没有保存抖音 Cookie 时添加会被拒绝；读取时登录失效会标记 `auth_expired`。别人的点赞列表不做（通常不公开）。
- **默认不自动下载**：点赞和收藏的 `auto_download` 缺省为 `false`（只同步列表），可在添加时显式开启；用户、合集沿用原来的默认。
- `GET /api/douyin/collections`：列出登录账号收藏的合集，供添加合集时选择。
- 点赞 / 收藏列表翻页间隔是博主作品的两倍，降低触发风控的概率。
- **同一作品只下载一次**：作品按平台作品 ID 跨订阅识别。某个订阅（例如“我的点赞”）已下载或正在下载的作品，在其他订阅（例如原作者）里首次出现时直接关联同一份文件——状态为已下载、不再入队；反过来，在别的订阅里手动下载一个已有文件的作品，也会直接关联（接口返回已有任务并带 `linked: true`，批量下载结果里单独计入 `linked`）。需要独立副本时用“重新下载”。检查 / 同步结果里 `linked_count` 是这类作品数。
- 文件和媒体库目录按**原作者**归类（点赞 / 收藏 / 合集订阅里的作品用作品自带的作者名，没有则用订阅名），不会另建“我的点赞”目录；订阅里仍然能看到并播放它们。
- **接口细节未经真机验证**：点赞 `…/aweme/favorite/`、收藏 `…/aweme/listcollection/`（POST 表单 `count` / `cursor`）、合集 `…/mix/aweme/`、`…/mix/detail/`、`…/mix/listcollection/` 的路径、参数与 `a_bogus` 对 POST 的签名方式来自网页端的公开行为，目前只用模拟响应测试。如果平台返回风控或格式错误，订阅会显示失败原因，不会误报“没有作品”。

## 订阅页

左侧订阅列表（搜索、平台筛选、状态标签），右侧订阅详情：检查状态与失败原因、立即检查、全量同步、播放；作品网格带状态筛选与计数、标题 / ID 搜索、分页、选择模式与批量下载、单项下载 / 重试 / 重新下载 / 播放 / 编辑 NFO / 移除记录、文件缺失清理；设置页（昵称、检查频率、自动下载、画质、NFO 开关）；添加、登录、导入 / 导出、删除均为对话框，破坏性操作有确认。

## 主要接口

| 接口 | 说明 |
| --- | --- |
| `POST /api/subscriptions` | 解析并添加订阅 |
| `GET /api/subscriptions`、`PATCH` / `DELETE /api/subscriptions/{id}` | 列表（含 `runtime` 状态）、编辑、删除 |
| `POST /api/subscriptions/{id}/check` | 立即增量检查 |
| `POST /api/subscriptions/{id}/sync` | 全量同步 |
| `GET /api/subscriptions/{id}/videos` | 作品分页，参数 `page` `page_size` `status` `q` |
| `GET /api/subscriptions/{id}/videos/stats` | 各状态计数 |
| `POST /api/subscriptions/{id}/videos/download` | 批量下载，`video_ids` 缺省为全部待下载 |
| `POST /api/subscriptions/{id}/videos/{video_id}/download` | 单项下载 / 重新下载 |
| `DELETE /api/subscriptions/{id}/videos/{video_id}` | 只移除列表记录，文件与任务保留 |
| `GET` / `PUT /api/subscriptions/{id}/videos/{video_id}/nfo` | 读取 / 编辑已有 NFO |
| `GET /api/backup/subscriptions`、`POST /api/backup/subscriptions/import` | 导出 / 导入 |
| `GET /api/files/{asset_id}/gallery` | 图集的全部图片与背景音乐 |
