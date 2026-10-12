# Harbor-DL Wiki

**Harbor-DL** 是一个自托管的个人媒体工作台：下载、订阅作者、录制直播，在浏览器里管理和播放自己的媒体库，并能整理成 Jellyfin / Emby 可直接识别的目录。后端 FastAPI + SQLite，前端 Vue 3 + Vite，另有 Android 配套 App。

![概览](images/dashboard.png)

## 从哪里开始

| 我想…… | 看这里 |
| --- | --- |
| 用 Docker 把它跑起来 | [[Quick Start]] |
| 第一次打开后该做什么 | [[First Steps]] |
| 认识界面上的每个页面 | [[UI Tour]] |
| 下载一个链接 | [[Downloads]] |
| 浏览、播放、沉浸式刷视频 | [[Library and Player]] |
| 订阅作者并自动同步 | [[Subscriptions]] |
| 登录抖音等平台并保存 Cookie | [[Browser Login]] |
| 接入 Jellyfin / Emby | [[Media Server Export]] |
| 录制 B 站直播 | [[Live Recording]] |
| 调整设置、代理、API Token | [[Settings and Configuration]] |
| 用手机刷自己的库 | [[Mobile App]] |
| 升级、备份、反向代理 | [[Deployment and Backup]] |
| 本地开发与测试 | [[Development]] |
| 遇到问题 | [[FAQ]] |
| 哪些功能已经做完 | [[Project Status]] |

## 一句话功能表

| 模块 | 能做什么 |
| --- | --- |
| 下载 | 粘贴链接或分享文本，解析元数据与格式（基于 yt-dlp）；队列、取消、重试；字幕与缩略图；全局代理与按平台保存的 Cookie |
| 媒体库 | 下载的文件自动入库；类型筛选、搜索、排序；同一作品的图片与音乐合并为一张卡片；可切换封面比例 |
| 播放器 | 快速预览、全屏竖滑沉浸播放、图集轮播 + 背景音乐、断点续播、地址栏记录当前播放 |
| 作者订阅 | 抖音博主 / 我的点赞 / 我的收藏 / 合集；YouTube 频道、歌单、Shorts；B 站作者；定时检查与自动下载 |
| 媒体服务器导出 | 每个视频生成「作者 / 标题 [作品ID]」文件夹，含视频、封面和标准 NFO |
| 内嵌浏览器登录 | 在专用 Chrome 用户目录里登录平台并保存 Cookie；Docker 部署通过 noVNC 嵌在页面中 |
| 直播 | B 站直播间检测、周期监控、TS 录制与录制历史 |
| 账号与安全 | 首次启动创建管理员；会话登录；API Token（只读 / 下载 / 管理三档权限） |

> 本 Wiki 的截图来自一个全新的演示实例，演示视频是用 ffmpeg 生成的测试图案，不含任何真实平台内容。

## 项目链接

- 源码与 Issues：<https://github.com/rappa850/harbor-dl>
- 预构建镜像：`ghcr.io/rappa850/harbor-dl`
- 许可：MIT，第三方组件见仓库根目录 `THIRD_PARTY_NOTICES.md`
