import 'dart:async';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import 'api.dart';
import 'console_api.dart';
import 'console_models.dart';
import 'subscription_settings.dart';
import 'widgets.dart';

/// One subscription's control panel: check, sync, download in batches, per-work actions, settings, delete.
class SubscriptionPage extends StatefulWidget {
  const SubscriptionPage({super.key, required this.api, required this.subscriptionId, required this.onLogout, required this.onPlay});

  final Api api;
  final String subscriptionId;
  final VoidCallback onLogout;
  final Future<void> Function(FeedItem item) onPlay;

  @override
  State<SubscriptionPage> createState() => _SubscriptionPageState();
}

class _SubscriptionPageState extends State<SubscriptionPage> {
  static const _pageSize = 30;

  Subscription? _sub;
  WorkStats? _stats;
  final _works = <SubWork>[];
  int _total = 0, _page = 1;
  String _filter = 'all';
  bool _loadingMore = false, _loaded = false;
  String? _error;

  /// 'check' | 'sync' | 'download' while a request of ours is in flight (the server may also be busy on its own).
  String? _action;
  SyncProgress? _progress;
  Timer? _timer;
  final _selected = <String>{};

  Api get _api => widget.api;
  String get _id => widget.subscriptionId;
  bool get _selecting => _selected.isNotEmpty;
  bool get _working => _action != null || (_sub?.runtime.isSyncing ?? false) || _progress != null;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _say(String text) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _logout() async {
    await Session.clear();
    widget.onLogout();
  }

  /// Run a call; shows its failure as a message. Returns null on failure.
  Future<T?> _try<T>(Future<T> Function() call) async {
    try {
      return await call();
    } on Unauthorized {
      await _logout();
    } catch (e) {
      _say('$e');
    }
    return null;
  }

  /// Like [_try] for calls that return nothing: true when it went through.
  Future<bool> _ok(Future<void> Function() call) async => await _try(() async {
        await call();
        return true;
      }) ??
      false;

  Future<void> _reload() async {
    try {
      final results = await Future.wait([_api.subscription(_id), _api.workStats(_id), _api.subscriptionWorks(_id, pageSize: _pageSize, status: _filter)]);
      if (!mounted) return;
      final page = results[2] as WorkPage;
      setState(() {
        _sub = results[0] as Subscription;
        _stats = results[1] as WorkStats;
        _works
          ..clear()
          ..addAll(page.items);
        _total = page.total;
        _page = 1;
        _loaded = true;
        _error = null;
        _selected.clear();
      });
      _syncTimer();
    } on Unauthorized {
      await _logout();
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  Future<void> _loadMore() async {
    if (_loadingMore || _works.length >= _total) return;
    setState(() => _loadingMore = true);
    final page = await _try(() => _api.subscriptionWorks(_id, page: _page + 1, pageSize: _pageSize, status: _filter));
    if (!mounted) return;
    setState(() {
      _loadingMore = false;
      if (page != null) {
        _page++;
        _works.addAll(page.items.where((w) => !_works.any((o) => o.id == w.id)));
      }
    });
  }

  /// Keep a timer running while anything is syncing or downloading; stop it (and reload once) when it all settles.
  void _syncTimer() {
    final busy = _working || (_stats?.downloading ?? 0) > 0;
    if (busy && _timer == null) {
      _timer = Timer.periodic(const Duration(seconds: 3), (_) => _tick());
    } else if (!busy) {
      _timer?.cancel();
      _timer = null;
    }
  }

  bool _ticking = false;

  Future<void> _tick() async {
    if (_ticking || !mounted) return;
    _ticking = true;
    try {
      final progress = await _api.syncProgress(_id);
      final sub = await _api.subscription(_id);
      final stats = await _api.workStats(_id);
      if (!mounted) return;
      final wasWorking = _working || (_stats?.downloading ?? 0) > 0;
      setState(() {
        _progress = progress;
        _sub = sub;
        _stats = stats;
      });
      final nowBusy = _action != null || sub.runtime.isSyncing || progress != null || stats.downloading > 0;
      if (wasWorking && !nowBusy) await _reload();
      _syncTimer();
    } on Unauthorized {
      await _logout();
    } catch (_) {
      // a missed poll is fine
    } finally {
      _ticking = false;
    }
  }

  Future<void> _check() async {
    setState(() => _action = 'check');
    _syncTimer();
    final result = await _try(() => _api.checkNow(_id));
    if (result != null) _say(result.summary);
    if (mounted) setState(() => _action = null);
    await _reload();
  }

  Future<void> _sync() async {
    final ok = await _confirm('全量同步', '会读取这个订阅的全部历史作品，作品多时需要几分钟。可以离开此页，同步会在服务器上继续。开始吗？');
    if (!ok) return;
    setState(() => _action = 'sync');
    _syncTimer();
    final added = await _try(() => _api.fullSync(_id));
    if (added != null) _say(added > 0 ? '同步完成，新增 $added 个作品' : '同步完成，没有新作品');
    if (mounted) setState(() => _action = null);
    await _reload();
  }

  Future<void> _downloadAll() async {
    final stats = _stats;
    if (stats == null || stats.pending == 0) {
      _say('没有需要下载的作品');
      return;
    }
    final ok = await _confirm('下载全部未下载', '将把 ${stats.pending} 个作品加入下载队列（已下载的会跳过）。占用空间和时间可能很大，确定吗？');
    if (ok) await _download(null, null);
  }

  Future<void> _downloadBatch() async {
    final pending = _stats?.pending ?? 0;
    if (pending == 0) {
      _say('没有需要下载的作品');
      return;
    }
    final size = await showModalBottomSheet<int>(
      context: context,
      builder: (sheet) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const ListTile(title: Text('下载最新的…'), subtitle: Text('按发布时间从新到旧，已下载的跳过')),
          for (final n in const [20, 50, 100])
            ListTile(leading: const Icon(Icons.download_outlined), title: Text('$n 个'), onTap: () => Navigator.pop(sheet, n)),
        ]),
      ),
    );
    if (size != null) await _download(null, size);
  }

  Future<void> _download(List<String>? ids, int? limit) async {
    setState(() => _action = 'download');
    final result = await _try(() => _api.downloadBatch(_id, ids: ids, limit: limit));
    if (result != null) _say(result.summary);
    if (mounted) setState(() => _action = null);
    await _reload();
  }

  Future<bool> _confirm(String title, String message, {String ok = '确定', bool danger = false}) async {
    final answer = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialog, false), child: const Text('取消')),
          FilledButton(
              style: danger ? FilledButton.styleFrom(backgroundColor: Colors.redAccent) : null,
              onPressed: () => Navigator.pop(dialog, true),
              child: Text(ok)),
        ],
      ),
    );
    return answer ?? false;
  }

  Future<void> _settings() async {
    final sub = _sub;
    if (sub == null) return;
    final changes = await editSubscriptionSettings(context, sub);
    if (changes == null) return;
    final updated = await _try(() => _api.editSubscription(_id, changes));
    if (updated != null) {
      _say('已保存');
      await _reload();
    }
  }

  Future<void> _cleanup() async {
    final missing = _stats?.orphaned ?? 0;
    if (missing == 0) {
      _say('没有文件缺失的作品');
      return;
    }
    final ok = await _confirm('清理文件缺失的作品', '$missing 个作品的文件已经不在服务器上。清理会重置它们的状态，之后可以重新下载。确定吗？');
    if (!ok) return;
    if (await _ok(() => _api.cleanupMissing(_id))) _say('已清理');
    await _reload();
  }

  Future<void> _delete() async {
    final ok = await _confirm('删除订阅', '删除后不再检查更新，作品记录会一并删除；已下载的文件保留。确定删除“${_sub?.nickname ?? ''}”吗？', ok: '删除', danger: true);
    if (!ok) return;
    if (await _ok(() => _api.deleteSubscription(_id)) && mounted) Navigator.pop(context);
  }

  Future<void> _removeSelected() async {
    final ids = _selected.toList();
    final ok = await _confirm('移除记录', '只移除这 ${ids.length} 条列表记录，文件和下载任务保留。确定吗？', ok: '移除', danger: true);
    if (!ok) return;
    for (final id in ids) {
      if (!await _ok(() => _api.removeWork(_id, id))) break;
    }
    await _reload();
  }

  Future<void> _tapWork(SubWork work) async {
    if (_selecting) {
      setState(() => _selected.contains(work.id) ? _selected.remove(work.id) : _selected.add(work.id));
      return;
    }
    if (work.playable) {
      await widget.onPlay(FeedItem(work.assetId!, work.title, _sub?.nickname ?? '', work.duration, '/api/files/${work.assetId}/poster',
          '/api/files/${work.assetId}/stream'));
      return;
    }
    if (work.pending) {
      final linked = await _try(() => _api.downloadOne(_id, work.id, redownload: work.status == 'orphaned'));
      if (linked != null) _say(linked ? '这个作品已在其他订阅下载过，直接关联' : '已加入下载');
      await _reload();
    }
  }

  void _longPress(SubWork work) => setState(() => _selected.contains(work.id) ? _selected.remove(work.id) : _selected.add(work.id));

  @override
  Widget build(BuildContext context) {
    final sub = _sub;
    return PopScope(
      canPop: !_selecting,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) setState(_selected.clear);
      },
      child: Scaffold(
        backgroundColor: Colors.black,
        bottomNavigationBar: _selecting
            ? SafeArea(
                child: Padding(
                padding: const EdgeInsets.all(8),
                child: Row(children: [
                  Text('已选 ${_selected.length}'),
                  const Spacer(),
                  TextButton(onPressed: _removeSelected, child: const Text('移除记录')),
                  FilledButton(onPressed: () => _download(_selected.toList(), null), child: const Text('下载所选')),
                ]),
              ))
            : null,
        body: SafeArea(
          child: Column(children: [
            BackBar(title: sub?.nickname ?? '订阅'),
            Expanded(
              child: !_loaded
                  ? Center(
                      child: _error == null
                          ? const CircularProgressIndicator()
                          : Column(mainAxisSize: MainAxisSize.min, children: [
                              Text(_error!, style: const TextStyle(color: Colors.white70)),
                              const SizedBox(height: 8),
                              OutlinedButton(onPressed: _reload, child: const Text('重试')),
                            ]))
                  : RefreshIndicator(
                      onRefresh: _reload,
                      child: NotificationListener<ScrollNotification>(
                        onNotification: (n) {
                          if (n.metrics.pixels > n.metrics.maxScrollExtent - 300) _loadMore();
                          return false;
                        },
                        child: ListView(children: [
                          _header(sub!),
                          if (_progress != null) _progressCard(_progress!),
                          ..._notices(sub),
                          _actions(sub),
                          _filters(),
                          if (_works.isEmpty)
                            const Padding(padding: EdgeInsets.all(32), child: Center(child: Text('没有作品', style: TextStyle(color: Colors.white54)))),
                          for (final work in _works) _workTile(work),
                          if (_loadingMore) const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator())),
                          const SizedBox(height: 32),
                        ]),
                      ),
                    ),
            ),
          ]),
        ),
      ),
    );
  }

  Widget _header(Subscription sub) {
    final runtime = sub.runtime;
    final lines = [
      sub.label,
      '${runtime.storedVideos} 个作品',
      if (_stats != null) '已下载 ${_stats!.downloaded}，待下载 ${_stats!.pending}',
      if (runtime.checkAvailable) '上次检查 ${relativeTime(runtime.lastCheckedAt)}${runtime.lastMode != null ? '，新增 ${runtime.lastNew} 个' : ''}',
      if (runtime.nextCheckAt != null && !sub.paused) '下次检查 ${relativeTime(runtime.nextCheckAt, future: true)}',
      intervalLabel(sub.updateInterval),
    ];
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
      child: Text(lines.join(' · '), style: const TextStyle(color: Colors.white60, fontSize: 12, height: 1.6)),
    );
  }

  Widget _progressCard(SyncProgress progress) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(progress.text, style: const TextStyle(color: Colors.lightBlueAccent, fontSize: 13)),
          const SizedBox(height: 6),
          LinearProgressIndicator(value: progress.queued ? null : progress.fraction),
        ]),
      );

  List<Widget> _notices(Subscription sub) {
    final runtime = sub.runtime;
    Widget notice(String text, {Color color = Colors.orangeAccent}) => Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: Text(text, style: TextStyle(color: color, fontSize: 13, height: 1.5)),
        );
    return [
      if (runtime.authExpired) notice('抖音登录已失效，自动检查读不到作品。手机上不能登录，请在网页端重新登录抖音。')
      else if (runtime.lastError != null) notice('最近一次检查失败：${runtime.lastError}'),
      if (runtime.moreAvailable) notice('最近一次检查读满了页数上限，可能还有更早的新作品，建议全量同步。'),
      if (!runtime.checkAvailable && runtime.unavailableReason != null) notice(runtime.unavailableReason!, color: Colors.white54),
    ];
  }

  Widget _actions(Subscription sub) {
    final runtime = sub.runtime;
    final busy = _working;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
      child: Wrap(spacing: 8, runSpacing: 8, children: [
        if (runtime.checkAvailable)
          FilledButton.icon(
              onPressed: busy ? null : _check,
              icon: _action == 'check' ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.refresh, size: 18),
              label: const Text('检查更新')),
        if (runtime.manualSyncAvailable)
          OutlinedButton.icon(onPressed: busy ? null : _sync, icon: const Icon(Icons.history, size: 18), label: const Text('全量同步')),
        OutlinedButton.icon(onPressed: _action == 'download' ? null : _downloadAll, icon: const Icon(Icons.download, size: 18), label: const Text('下载全部')),
        OutlinedButton.icon(onPressed: _action == 'download' ? null : _downloadBatch, icon: const Icon(Icons.format_list_numbered, size: 18), label: const Text('分批下载')),
        PopupMenuButton<String>(
          icon: const Icon(Icons.more_horiz),
          onSelected: (v) => switch (v) { 'settings' => _settings(), 'cleanup' => _cleanup(), _ => _delete() },
          itemBuilder: (_) => const [
            PopupMenuItem(value: 'settings', child: Text('订阅设置')),
            PopupMenuItem(value: 'cleanup', child: Text('清理文件缺失的记录')),
            PopupMenuItem(value: 'delete', child: Text('删除订阅', style: TextStyle(color: Colors.redAccent))),
          ],
        ),
      ]),
    );
  }

  Widget _filters() {
    final stats = _stats;
    int count(String id) => switch (id) {
          'all' => stats?.total ?? 0,
          'downloaded' => stats?.downloaded ?? 0,
          'downloading' => stats?.downloading ?? 0,
          'not_downloaded' => stats?.notDownloaded ?? 0,
          'failed' => stats?.failed ?? 0,
          'orphaned' => stats?.orphaned ?? 0,
          _ => 0,
        };
    return SizedBox(
      height: 48,
      child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 12), children: [
        for (final (id, label) in kWorkStatuses)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
            child: ChoiceChip(
              label: Text('$label ${count(id)}'),
              selected: _filter == id,
              onSelected: (_) {
                setState(() => _filter = id);
                _reload();
              },
            ),
          ),
      ]),
    );
  }

  Widget _workTile(SubWork work) {
    final selected = _selected.contains(work.id);
    final color = switch (work.status) {
      'downloaded' => Colors.greenAccent,
      'downloading' => Colors.lightBlueAccent,
      'failed' || 'orphaned' => Colors.orangeAccent,
      _ => Colors.white54,
    };
    final progress = work.status == 'downloading' && work.progress != null ? ' ${work.progress!.round()}%' : '';
    return ListTile(
      selected: selected,
      selectedTileColor: Colors.white10,
      onTap: () => _tapWork(work),
      onLongPress: () => _longPress(work),
      leading: SizedBox(
        width: 56,
        height: 56,
        child: ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: selected
              ? const ColoredBox(color: Colors.teal, child: Icon(Icons.check, color: Colors.white))
              : work.cover == null
                  ? const ColoredBox(color: Colors.white12)
                  : CachedNetworkImage(
                      imageUrl: work.cover!.startsWith('http') ? work.cover! : _api.session.url(work.cover!),
                      httpHeaders: work.cover!.startsWith('http') ? null : _api.session.headers,
                      fit: BoxFit.cover,
                      errorWidget: (_, _, _) => const ColoredBox(color: Colors.white12)),
        ),
      ),
      title: Text(work.title, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white, fontSize: 14)),
      subtitle: Text(
        [
          if (work.author != null && _sub?.type != 'user') work.author!,
          if (work.publishTime != null && work.publishTime!.length >= 10) work.publishTime!.substring(0, 10),
          if (formatDuration(work.duration).isNotEmpty) formatDuration(work.duration),
        ].join(' · '),
        style: const TextStyle(color: Colors.white54, fontSize: 12),
      ),
      trailing: Text('${workStatusLabel(work.status, taskStatus: work.taskStatus)}$progress', style: TextStyle(color: color, fontSize: 12)),
    );
  }
}
