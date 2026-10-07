import 'dart:io';

import 'package:flutter/material.dart';

import 'api.dart';
import 'offline.dart';
import 'widgets.dart';

/// Videos saved on the phone: a grid that works without the server, plus "download all favorites" and a way to clear.
class OfflineTab extends StatefulWidget {
  const OfflineTab({super.key, required this.api, required this.onLogout});

  final Api api;
  final VoidCallback onLogout;

  @override
  State<OfflineTab> createState() => _OfflineTabState();
}

class _OfflineTabState extends State<OfflineTab> with AutomaticKeepAliveClientMixin {
  Offline? _offline;
  String? _progress;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    Offline.open(widget.api.session).then((offline) {
      if (mounted) setState(() => _offline = offline);
    });
  }

  void _say(String text) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));

  String _megabytes(int bytes) => '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';

  /// Walk every page of the favorites feed and save what is not on the phone yet.
  Future<void> _saveFavorites() async {
    final offline = _offline!;
    setState(() => _progress = '正在读取收藏…');
    var done = 0, failed = 0;
    try {
      String? cursor;
      do {
        final page = await widget.api.feed(cursor: cursor, mode: 'favorites', limit: 50);
        for (final item in page.items) {
          if (offline.has(item.id)) continue;
          if (mounted) setState(() => _progress = '正在保存 ${done + failed + 1}（共 ${page.total} 个收藏）');
          await offline.add(item) ? done++ : failed++;
        }
        cursor = page.next;
      } while (cursor != null && mounted);
    } on Unauthorized {
      widget.onLogout();
      return;
    } catch (e) {
      if (mounted) _say('$e');
    }
    if (!mounted) return;
    setState(() => _progress = null);
    _say(failed == 0 ? '已保存 $done 个视频' : '已保存 $done 个，$failed 个失败');
  }

  Future<void> _clear() async {
    final ok = await showDialog<bool>(
        context: context,
        builder: (dialog) => AlertDialog(
              title: const Text('清空离线视频？'),
              content: const Text('手机上保存的副本会被删除，服务器上的视频不受影响。'),
              actions: [
                TextButton(onPressed: () => Navigator.pop(dialog, false), child: const Text('取消')),
                TextButton(onPressed: () => Navigator.pop(dialog, true), child: const Text('清空')),
              ],
            ));
    if (ok != true) return;
    _offline!.clear();
    setState(() {});
  }

  Future<void> _open(List<FeedItem> items, int index) async {
    await openFeed(context, api: widget.api, onLogout: widget.onLogout, seed: FeedSeed(items, null, index), mode: 'offline');
    if (mounted) setState(() {}); // copies may have been removed while watching
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final offline = _offline;
    if (offline == null) return const Center(child: CircularProgressIndicator(strokeWidth: 2));
    final items = offline.items();
    return CustomScrollView(slivers: [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 8, 8),
          child: Row(children: [
            Expanded(
                child: Text(_progress ?? '${items.length} 个视频 · ${_megabytes(offline.size())}',
                    style: const TextStyle(color: Colors.white70, fontSize: 13))),
            TextButton.icon(
                onPressed: _progress == null ? _saveFavorites : null,
                icon: const Icon(Icons.download_outlined, size: 18),
                label: const Text('保存全部收藏')),
            if (items.isNotEmpty) IconButton(tooltip: '清空', onPressed: _clear, icon: const Icon(Icons.delete_outline, color: Colors.white70)),
          ]),
        ),
      ),
      if (items.isEmpty)
        const SliverFillRemaining(
            hasScrollBody: false,
            child: Center(child: Text('还没有离线视频，在播放页点下载按钮即可保存', style: TextStyle(color: Colors.white54))))
      else
        SliverGrid.builder(
          gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 3, mainAxisSpacing: 2, crossAxisSpacing: 2, childAspectRatio: 3 / 4),
          itemCount: items.length,
          itemBuilder: (context, i) {
            final item = items[i], length = formatDuration(item.duration);
            return GestureDetector(
              onTap: () => _open(items, i),
              child: Stack(fit: StackFit.expand, children: [
                ColoredBox(
                  color: Colors.white10,
                  child: item.localCover == null
                      ? const Icon(Icons.movie_outlined, color: Colors.white24)
                      : Image.file(File(item.localCover!), fit: BoxFit.cover, cacheWidth: 360, errorBuilder: (_, _, _) => const SizedBox()),
                ),
                if (length.isNotEmpty)
                  Positioned(
                      right: 6,
                      bottom: 4,
                      child: Text(length, style: const TextStyle(color: Colors.white, fontSize: 12, shadows: [Shadow(blurRadius: 4)]))),
              ]),
            );
          },
        ),
    ]);
  }
}
