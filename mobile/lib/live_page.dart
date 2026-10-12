import 'package:flutter/material.dart';

import 'api.dart';
import 'console_api.dart';
import 'console_models.dart';
import 'widgets.dart';

/// Live rooms: check whether they are on air, start / stop recording, switch monitoring, look at past recordings.
/// Adding a room is done with the backup import in the web page.
class LivePage extends StatefulWidget {
  const LivePage({super.key, required this.api, required this.onLogout});

  final Api api;
  final VoidCallback onLogout;

  @override
  State<LivePage> createState() => _LivePageState();
}

class _LivePageState extends State<LivePage> {
  List<LiveRoom>? _rooms;
  String? _error;
  final _busy = <String>{};

  Api get _api => widget.api;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _say(String text) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _load() async {
    try {
      final rooms = await _api.liveRooms();
      if (mounted) {
        setState(() {
          _rooms = rooms;
          _error = null;
        });
      }
    } on Unauthorized {
      await Session.clear();
      widget.onLogout();
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  Future<void> _run(LiveRoom room, Future<void> Function() call, {String? done}) async {
    setState(() => _busy.add(room.id));
    try {
      await call();
      if (done != null) _say(done);
    } on Unauthorized {
      await Session.clear();
      widget.onLogout();
      return;
    } catch (e) {
      _say('$e');
    } finally {
      if (mounted) setState(() => _busy.remove(room.id));
    }
    await _load();
  }

  Future<void> _records(LiveRoom room) async {
    try {
      final records = await _api.liveRecords(room.id);
      if (!mounted) return;
      await showModalBottomSheet<void>(
        context: context,
        builder: (_) => SafeArea(
          child: records.isEmpty
              ? const Padding(padding: EdgeInsets.all(32), child: Text('还没有录制记录'))
              : ListView(shrinkWrap: true, children: [
                  ListTile(title: Text('${room.name} 的录制记录')),
                  for (final record in records)
                    ListTile(
                      dense: true,
                      title: Text('${record.statusText} · ${record.startTime.length >= 16 ? record.startTime.substring(0, 16).replaceFirst('T', ' ') : record.startTime}'),
                      subtitle: Text([formatClock(record.duration), formatBytes(record.size), if (record.error.isNotEmpty) record.error].join(' · ')),
                    ),
                ]),
        ),
      );
    } on Unauthorized {
      await Session.clear();
      widget.onLogout();
    } catch (e) {
      _say('$e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final rooms = _rooms;
    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: Column(children: [
          const BackBar(title: '直播'),
          Expanded(
            child: rooms == null
                ? Center(
                    child: _error == null
                        ? const CircularProgressIndicator()
                        : Column(mainAxisSize: MainAxisSize.min, children: [
                            Text(_error!, style: const TextStyle(color: Colors.white70)),
                            const SizedBox(height: 8),
                            OutlinedButton(onPressed: _load, child: const Text('重试')),
                          ]))
                : RefreshIndicator(
                    onRefresh: _load,
                    child: rooms.isEmpty
                        ? ListView(children: const [
                            SizedBox(height: 120),
                            Center(child: Padding(padding: EdgeInsets.all(24), child: Text('没有直播订阅。请在网页端“直播”页面导入直播间配置。', style: TextStyle(color: Colors.white54)))),
                          ])
                        : ListView.separated(
                            itemCount: rooms.length,
                            separatorBuilder: (_, _) => const Divider(height: 1, color: Colors.white10),
                            itemBuilder: (_, i) => _tile(rooms[i]),
                          ),
                  ),
          ),
        ]),
      ),
    );
  }

  Widget _tile(LiveRoom room) {
    final busy = _busy.contains(room.id);
    final color = room.recording ? Colors.redAccent : (room.isLive == true ? Colors.greenAccent : Colors.white54);
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(room.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w600))),
          Text(room.stateText, style: TextStyle(color: color)),
        ]),
        const SizedBox(height: 4),
        Text([subscriptionLabel(room.platform, 'user'), if (room.checkedAt != null) '检测于 ${relativeTime(room.checkedAt)}'].join(' · '), style: const TextStyle(color: Colors.white54, fontSize: 12)),
        if (room.error != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(room.error!, style: const TextStyle(color: Colors.orangeAccent, fontSize: 12))),
        if (!room.recordingAvailable && room.reason != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(room.reason!, style: const TextStyle(color: Colors.white38, fontSize: 12))),
        const SizedBox(height: 8),
        Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
          OutlinedButton(onPressed: busy ? null : () => _run(room, () => _api.checkLiveRoom(room.id)), child: Text(busy ? '处理中…' : '检测')),
          if (room.recording)
            FilledButton(
                style: FilledButton.styleFrom(backgroundColor: Colors.redAccent),
                onPressed: busy ? null : () => _run(room, () => _api.stopRecording(room.id), done: '已停止录制'),
                child: const Text('停止录制'))
          else if (room.recordingAvailable)
            FilledButton(onPressed: busy ? null : () => _run(room, () => _api.startRecording(room.id), done: '已开始录制'), child: const Text('开始录制')),
          TextButton(onPressed: () => _records(room), child: const Text('录制记录')),
        ]),
        SwitchListTile(
            contentPadding: EdgeInsets.zero,
            dense: true,
            title: const Text('周期监控'),
            value: room.monitorEnabled,
            onChanged: room.monitorAvailable && !busy ? (v) => _run(room, () => _api.editLiveRoom(room.id, {'monitor_enabled': v})) : null),
        SwitchListTile(
            contentPadding: EdgeInsets.zero,
            dense: true,
            title: const Text('开播自动录制'),
            value: room.autoRecord,
            onChanged: room.recordingAvailable && !busy ? (v) => _run(room, () => _api.editLiveRoom(room.id, {'auto_record': v})) : null),
      ]),
    );
  }
}
