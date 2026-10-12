# Live Recording

目前支持 **B 站直播**：检测是否开播、周期监控、TS 录制和录制历史。其他平台、录制时段、分段、后处理、弹幕等还没有做，见 [[Project Status]]。

![直播配置](images/live.png)

## 配置直播间

「直播配置」页通过 **直播订阅备份 JSON** 导入直播间，导入后每个直播间会显示为一张可编辑的配置卡片，保留直播间、录制选项和扩展配置。页面里的输入框给出了格式示例：

```json
{"subscriptions":[{"platform":"douyin","room_url":"https://live.douyin.com/直播间"}]}
```

把 `platform` 和 `room_url` 换成你要监控的平台与直播间地址，点「导入直播备份」。「导出直播配置」可以把当前配置导出备份。

## 录制与监控

- 检测直播间是否开播；
- 开始 / 停止手动录制；
- 周期监控，开播后自动录制；
- 录制输出为 TS，保存在数据目录的 `recordings/`；
- 录制历史可以在页面里查看。

## 注意

- 录制依赖 FFmpeg。
- 直播录制功能尚未完成，其中 4 个依赖真实 ffmpeg 的测试在 Linux（GitHub CI）上被跳过，Windows 上通过。
- 手机 App 里也有直播入口（订阅页右上角），见 [[Mobile App]]。
