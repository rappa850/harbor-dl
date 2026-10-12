import 'package:flutter/material.dart';

import 'api.dart';
import 'console_api.dart';
import 'console_models.dart';
import 'widgets.dart';

const _platformTitles = {'douyin': '抖音', 'youtube': 'YouTube', 'bilibili': '哔哩哔哩'};

/// Server health and settings: disk, queue counts, concurrency, saved platform logins, recent failures.
/// Logging in to a platform, changing the password and managing tokens stay in the web page.
class SystemPage extends StatefulWidget {
  const SystemPage({super.key, required this.api, required this.onLogout});

  final Api api;
  final VoidCallback onLogout;

  @override
  State<SystemPage> createState() => _SystemPageState();
}

class _SystemPageState extends State<SystemPage> {
  Overview? _overview;
  ServerSettings? _settings;
  CookieStatus? _cookies;
  List<LogEntry>? _logs;
  String _logSource = '';
  String? _error;
  int _downloads = 2, _syncs = 1;
  bool _dirty = false, _saving = false;

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
      final results = await Future.wait<Object>([_api.overview(), _api.serverSettings(), _api.cookieStatus(), _api.failureLogs(source: _logSource)]);
      if (!mounted) return;
      final settings = results[1] as ServerSettings;
      setState(() {
        _overview = results[0] as Overview;
        _settings = settings;
        _cookies = results[2] as CookieStatus;
        _logs = results[3] as List<LogEntry>;
        _downloads = settings.concurrency;
        _syncs = settings.syncConcurrency;
        _dirty = false;
        _error = null;
      });
    } on Unauthorized {
      await Session.clear();
      widget.onLogout();
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  Future<void> _reloadLogs(String source) async {
    setState(() => _logSource = source);
    try {
      final logs = await _api.failureLogs(source: source);
      if (mounted && source == _logSource) setState(() => _logs = logs);
    } on Unauthorized {
      await Session.clear();
      widget.onLogout();
    } catch (e) {
      _say('$e');
    }
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      await _api.saveConcurrency(downloads: _downloads, syncs: _syncs);
      _say('已保存');
      await _load();
    } on Unauthorized {
      await Session.clear();
      widget.onLogout();
    } catch (e) {
      _say('$e');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Widget _section(String title, List<Widget> children) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          ...children,
        ]),
      );

  Widget _stepper(String label, int value, int min, int max, ValueChanged<int> onChanged) => Row(children: [
        Expanded(child: Text(label, style: const TextStyle(color: Colors.white70))),
        IconButton(onPressed: value > min ? () => onChanged(value - 1) : null, icon: const Icon(Icons.remove_circle_outline)),
        SizedBox(width: 24, child: Text('$value', textAlign: TextAlign.center, style: const TextStyle(color: Colors.white))),
        IconButton(onPressed: value < max ? () => onChanged(value + 1) : null, icon: const Icon(Icons.add_circle_outline)),
      ]);

  @override
  Widget build(BuildContext context) {
    final overview = _overview, settings = _settings;
    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: Column(children: [
          const BackBar(title: '服务器状态'),
          Expanded(
            child: overview == null || settings == null
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
                    child: ListView(children: [
                      _section('运行状态', [
                        Text('版本 ${settings.version} · FFmpeg ${settings.ffmpeg ? '可用' : '未检测到'}', style: const TextStyle(color: Colors.white70)),
                        const SizedBox(height: 8),
                        Text('下载中 ${overview.running} · 排队 ${overview.queued} · 失败 ${overview.failed}', style: const TextStyle(color: Colors.white70)),
                        const SizedBox(height: 12),
                        LinearProgressIndicator(value: overview.diskUsedFraction),
                        const SizedBox(height: 6),
                        Text('磁盘剩余 ${formatBytes(overview.diskFree)} / ${formatBytes(overview.diskTotal)} · 已下载 ${formatBytes(overview.downloadedBytes)}',
                            style: const TextStyle(color: Colors.white54, fontSize: 12)),
                      ]),
                      _section('并发', [
                        _stepper('同时下载的任务数', _downloads, 1, 8, (v) => setState(() {
                              _downloads = v;
                              _dirty = true;
                            })),
                        _stepper('同时同步的订阅数', _syncs, 1, 3, (v) => setState(() {
                              _syncs = v;
                              _dirty = true;
                            })),
                        const Text('数值越小，对平台的请求越少，越不容易触发风控。', style: TextStyle(color: Colors.white54, fontSize: 12)),
                        if (_dirty) Align(alignment: Alignment.centerRight, child: FilledButton(onPressed: _saving ? null : _save, child: const Text('保存'))),
                      ]),
                      _section('平台登录状态', [
                        for (final entry in (_cookies?.saved.entries ?? const <MapEntry<String, String?>>[]).where((e) => _platformTitles.containsKey(e.key)))
                          ListTile(
                            contentPadding: EdgeInsets.zero,
                            dense: true,
                            leading: Icon(entry.value == null ? Icons.close : Icons.check_circle_outline, color: entry.value == null ? Colors.white38 : Colors.greenAccent),
                            title: Text(_platformTitles[entry.key]!, style: const TextStyle(color: Colors.white)),
                            subtitle: Text(entry.value == null ? '未保存登录状态' : '已保存 · ${relativeTime(entry.value)}', style: const TextStyle(color: Colors.white54)),
                          ),
                        const Text('保存状态不代表登录仍然有效；失效时订阅会显示“需要重新登录”。手机上不能登录，请在网页端登录。', style: TextStyle(color: Colors.white54, fontSize: 12)),
                      ]),
                      _section('最近的失败', [
                        Wrap(spacing: 8, children: [
                          for (final (id, label) in const [('', '全部'), ('task', '下载'), ('subscription', '订阅'), ('live', '直播')])
                            ChoiceChip(label: Text(label), selected: _logSource == id, onSelected: (_) => _reloadLogs(id)),
                        ]),
                        if (_logs == null || _logs!.isEmpty)
                          const Padding(padding: EdgeInsets.symmetric(vertical: 16), child: Text('没有失败记录', style: TextStyle(color: Colors.white54)))
                        else
                          for (final log in _logs!)
                            ListTile(
                              contentPadding: EdgeInsets.zero,
                              dense: true,
                              title: Text('${log.sourceText} · ${log.title}', maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white)),
                              subtitle: Text('${log.message}\n${relativeTime(log.time)}', maxLines: 4, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white54, fontSize: 12)),
                              isThreeLine: true,
                            ),
                      ]),
                      const SizedBox(height: 32),
                    ]),
                  ),
          ),
        ]),
      ),
    );
  }
}
