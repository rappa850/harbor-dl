import 'dart:async';

import 'package:flutter/material.dart';

import 'add_download_page.dart';
import 'api.dart';
import 'console_api.dart';
import 'console_models.dart';

/// The download queue: what is running, waiting, done or failed, with cancel / retry / delete, and a way to add a link.
class DownloadsPage extends StatefulWidget {
  const DownloadsPage({super.key, required this.api, required this.onLogout, this.active = true});

  final Api api;
  final VoidCallback onLogout;
  final bool active;

  @override
  State<DownloadsPage> createState() => _DownloadsPageState();
}

class _DownloadsPageState extends State<DownloadsPage> {
  static const _pageSize = 30;

  final _items = <TaskRow>[];
  int _total = 0;
  String _filter = 'all';
  bool _loaded = false, _loadingMore = false;
  String? _error;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 3), (_) {
      // follow running downloads, but leave the server alone while the tab is hidden or nothing moves
      if (widget.active && _items.any((t) => t.active)) _load(quiet: true);
    });
  }

  @override
  void didUpdateWidget(DownloadsPage old) {
    super.didUpdateWidget(old);
    if (!old.active && widget.active) _load(quiet: true);
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

  /// [quiet] keeps the loaded rows (and as many of them as are on screen) instead of resetting the scroll.
  Future<void> _load({bool quiet = false}) async {
    final filter = _filter;
    try {
      final keep = quiet ? _items.length.clamp(_pageSize, 500) : _pageSize;
      final page = await widget.api.tasks(status: filter, limit: keep);
      if (!mounted || filter != _filter) return;
      setState(() {
        _items
          ..clear()
          ..addAll(page.items);
        _total = page.total;
        _loaded = true;
        _error = null;
      });
    } on Unauthorized {
      await _logout();
    } catch (e) {
      if (mounted && !quiet) setState(() => _error = '$e');
    }
  }

  Future<void> _loadMore() async {
    if (_loadingMore || _items.length >= _total) return;
    setState(() => _loadingMore = true);
    try {
      final page = await widget.api.tasks(status: _filter, offset: _items.length, limit: _pageSize);
      if (mounted) setState(() => _items.addAll(page.items.where((t) => !_items.any((o) => o.id == t.id))));
    } on Unauthorized {
      await _logout();
    } catch (e) {
      _say('$e');
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  Future<void> _act(Future<void> Function() call, {String? done}) async {
    try {
      await call();
      if (done != null) _say(done);
    } on Unauthorized {
      await _logout();
      return;
    } catch (e) {
      _say('$e');
    }
    await _load(quiet: true);
  }

  Future<void> _add() async {
    final added = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => AddDownloadPage(api: widget.api, onLogout: widget.onLogout)));
    if (added == true) _load(quiet: true);
  }

  Future<void> _delete(TaskRow task) async {
    final choice = await showModalBottomSheet<String>(
      context: context,
      builder: (sheet) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(title: Text(task.title, maxLines: 2, overflow: TextOverflow.ellipsis)),
          ListTile(leading: const Icon(Icons.playlist_remove), title: const Text('只删除任务记录'), subtitle: const Text('已下载的文件保留'), onTap: () => Navigator.pop(sheet, 'record')),
          ListTile(
              leading: const Icon(Icons.delete_forever, color: Colors.redAccent),
              title: const Text('同时删除文件', style: TextStyle(color: Colors.redAccent)),
              subtitle: const Text('文件从服务器上删除，其他订阅里关联同一文件的作品也会受影响'),
              onTap: () => Navigator.pop(sheet, 'file')),
        ]),
      ),
    );
    if (choice != null) await _act(() => widget.api.deleteTask(task.id, deleteFile: choice == 'file'));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      floatingActionButton: FloatingActionButton.extended(onPressed: _add, icon: const Icon(Icons.add_link), label: const Text('添加链接')),
      body: SafeArea(
        bottom: false,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Padding(
              padding: EdgeInsets.fromLTRB(16, 12, 16, 4),
              child: Text('下载', style: TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.w700))),
          SizedBox(
            height: 48,
            child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 12), children: [
              for (final (id, label) in kTaskFilters)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
                  child: ChoiceChip(
                    label: Text(label),
                    selected: _filter == id,
                    onSelected: (_) {
                      setState(() {
                        _filter = id;
                        _loaded = false;
                      });
                      _load();
                    },
                  ),
                ),
            ]),
          ),
          Expanded(
            child: !_loaded
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
                    child: NotificationListener<ScrollNotification>(
                      onNotification: (n) {
                        if (n.metrics.pixels > n.metrics.maxScrollExtent - 300) _loadMore();
                        return false;
                      },
                      child: _items.isEmpty
                          ? ListView(children: const [SizedBox(height: 120), Center(child: Text('没有任务', style: TextStyle(color: Colors.white54)))])
                          : ListView.separated(
                              padding: const EdgeInsets.only(bottom: 96),
                              itemCount: _items.length,
                              separatorBuilder: (_, _) => const Divider(height: 1, color: Colors.white10),
                              itemBuilder: (_, i) => _TaskTile(
                                task: _items[i],
                                onCancel: () => _act(() => widget.api.cancelTask(_items[i].id)),
                                onRetry: () => _act(() => widget.api.retryTask(_items[i].id), done: '已重新加入队列'),
                                onDelete: () => _delete(_items[i]),
                              ),
                            ),
                    ),
                  ),
          ),
        ]),
      ),
    );
  }
}

class _TaskTile extends StatelessWidget {
  const _TaskTile({required this.task, required this.onCancel, required this.onRetry, required this.onDelete});

  final TaskRow task;
  final VoidCallback onCancel, onRetry, onDelete;

  @override
  Widget build(BuildContext context) {
    final color = switch (task.status) {
      'COMPLETED' => Colors.greenAccent,
      'ERROR' => Colors.orangeAccent,
      'DOWNLOADING' || 'PROCESSING' => Colors.lightBlueAccent,
      _ => Colors.white54,
    };
    return ListTile(
      title: Text(task.title, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white, fontSize: 14)),
      subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const SizedBox(height: 4),
        Text([task.statusText, if (task.status == 'DOWNLOADING') '${task.progress.round()}%', if (task.speed.isNotEmpty && task.active) task.speed, if (task.author?.isNotEmpty == true) task.author!].join(' · '),
            style: TextStyle(color: color, fontSize: 12)),
        if (task.status == 'DOWNLOADING') Padding(padding: const EdgeInsets.only(top: 6), child: LinearProgressIndicator(value: task.progress > 0 ? (task.progress / 100).clamp(0.0, 1.0).toDouble() : null)),
        if (task.status == 'ERROR' && task.error != null)
          Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(task.error!, maxLines: 3, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white54, fontSize: 12))),
      ]),
      trailing: PopupMenuButton<String>(
        icon: const Icon(Icons.more_vert, color: Colors.white54),
        onSelected: (v) => switch (v) { 'cancel' => onCancel(), 'retry' => onRetry(), _ => onDelete() },
        itemBuilder: (_) => [
          if (task.active) const PopupMenuItem(value: 'cancel', child: Text('取消')),
          if (task.canRetry) const PopupMenuItem(value: 'retry', child: Text('重试')),
          if (!task.active) const PopupMenuItem(value: 'delete', child: Text('删除', style: TextStyle(color: Colors.redAccent))),
        ],
      ),
    );
  }
}
