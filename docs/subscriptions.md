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
- **下载（不需要登录）**：任务开始时才取作品详情，**不使用已保存的登录 Cookie**，只用代理。做法是用一次性匿名无头 Chrome（临时用户目录，用后删除）打开作品页，等页面自带签名脚本就绪后在页面里请求详情接口。
  - 视频：取最高码率，去掉水印路径；音乐轨不会被当成视频。
  - 图集：下载全部图片（多为 webp）和背景音乐（`_bgm.mp3`，失败不影响图片），第一张图为主文件；任何一张图被拦截则任务失败。

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
