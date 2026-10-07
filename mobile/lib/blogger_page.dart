import 'dart:async';
import 'dart:ui';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import 'api.dart';
import 'video_grid.dart';
import 'widgets.dart';

const _platforms = {'douyin': '抖音', 'bilibili': '哔哩哔哩', 'youtube': 'YouTube', 'youtube_playlist': 'YouTube'};

String platformLabel(String id) => _platforms[id] ?? id;

/// Opens a blogger's page; completes when the user comes back.
Future<void> openBlogger(BuildContext context, Api api, VoidCallback onLogout, String author, {Blogger? known}) {
  return Navigator.of(context).push(MaterialPageRoute<void>(
      builder: (_) => BloggerPage(api: api, onLogout: onLogout, author: author, known: known)));
}

/// Profile header (avatar, signature, numbers) with the blogger's videos as a cover grid underneath, newest first.
class BloggerPage extends StatefulWidget {
  const BloggerPage({super.key, required this.api, required this.onLogout, required this.author, this.known});

  final Api api;
  final VoidCallback onLogout;
  final String author;

  /// What the list already knew about this blogger, shown immediately while the detail loads.
  final Blogger? known;

  @override
  State<BloggerPage> createState() => _BloggerPageState();
}

class _BloggerPageState extends State<BloggerPage> {
  late Blogger? _info = widget.known;
  List<RemoteWork> _works = [];
  int _epoch = 0;
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    _load();
    _loadWorks();
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _loadWorks() async {
    try {
      final fresh = await widget.api.works(widget.author);
      if (!mounted) return;
      // a work that was downloading and is no longer listed has finished: it now belongs to the playable grid
      final finished = _works.any((w) => w.status == 'downloading' && !fresh.any((f) => f.id == w.id));
      setState(() {
        _works = fresh;
        if (finished) _epoch++;
      });
      if (finished) _load();
      _schedulePoll();
    } on Unauthorized {
      widget.onLogout();
    } catch (_) {
      // the downloaded grid still works without this list
    }
  }

  void _schedulePoll() {
    _poll?.cancel();
    if (_works.any((w) => w.status == 'downloading')) _poll = Timer(const Duration(seconds: 5), _loadWorks);
  }

  Future<void> _request(RemoteWork work) async {
    final ok = await showDialog<bool>(
        context: context,
        builder: (dialog) => AlertDialog(
              title: const Text('下载到服务器？'),
              content: Text(work.title.isEmpty ? '这个作品还没有下载' : work.title, maxLines: 4, overflow: TextOverflow.ellipsis),
              actions: [
                TextButton(onPressed: () => Navigator.pop(dialog, false), child: const Text('取消')),
                TextButton(onPressed: () => Navigator.pop(dialog, true), child: const Text('下载')),
              ],
            ));
    if (ok != true) return;
    try {
      await widget.api.downloadWork(work);
      if (!mounted) return;
      setState(() => work.status = 'downloading');
      _schedulePoll();
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('已提交下载，完成后会出现在上面的视频里')));
    } on Unauthorized {
      widget.onLogout();
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> _load() async {
    try {
      final fresh = await widget.api.blogger(widget.author);
      if (mounted) setState(() => _info = fresh);
    } on Unauthorized {
      widget.onLogout();
    } catch (_) {
      // the header keeps what the list knew; the grid reports its own errors
    }
  }

  List<Widget> _remoteSlivers() {
    final session = widget.api.session;
    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 20, 16, 8),
          child: Text('未下载的作品 · ${_works.length}（已同步，点击可请求下载）', style: const TextStyle(color: Colors.white70, fontSize: 13)),
        ),
      ),
      SliverGrid.builder(
        gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: 3, mainAxisSpacing: 2, crossAxisSpacing: 2, childAspectRatio: 3 / 4),
        itemCount: _works.length,
        itemBuilder: (context, i) {
          final work = _works[i], busy = work.status == 'downloading', length = formatDuration(work.duration);
          return GestureDetector(
            onTap: busy ? null : () => _request(work),
            child: Stack(fit: StackFit.expand, children: [
              ColoredBox(
                color: Colors.white10,
                child: work.cover == null
                    ? const SizedBox()
                    : CachedNetworkImage(
                        imageUrl: session.url(work.cover!),
                        httpHeaders: session.headers,
                        fit: BoxFit.cover,
                        memCacheWidth: 360,
                        errorWidget: (_, _, _) => const SizedBox()),
              ),
              const ColoredBox(color: Color(0x88000000)),
              Center(
                  child: busy
                      ? const SizedBox(width: 26, height: 26, child: CircularProgressIndicator(strokeWidth: 2))
                      : Icon(work.status == 'failed' ? Icons.error_outline : Icons.cloud_download_outlined, color: Colors.white70, size: 30)),
              Positioned(
                  left: 6,
                  bottom: 4,
                  child: Text(_statusText[work.status] ?? work.status, style: const TextStyle(color: Colors.white, fontSize: 11, shadows: [Shadow(blurRadius: 4)]))),
              if (length.isNotEmpty)
                Positioned(right: 6, top: 4, child: Text(length, style: const TextStyle(color: Colors.white, fontSize: 11, shadows: [Shadow(blurRadius: 4)]))),
            ]),
          );
        },
      ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final session = widget.api.session, info = _info;
    return Scaffold(
      backgroundColor: Colors.black,
      body: NestedScrollView(
        headerSliverBuilder: (context, _) => [
          SliverToBoxAdapter(child: _Header(session: session, author: widget.author, info: info)),
        ],
        body: VideoGrid(
          api: widget.api,
          mode: 'latest',
          author: widget.author,
          emptyText: '还没有已下载的视频',
          refresh: _epoch,
          trailing: [if (_works.isNotEmpty) ..._remoteSlivers()],
          onOpen: (seed) => openFeed(context, api: widget.api, onLogout: widget.onLogout, seed: seed, mode: 'latest', author: widget.author),
        ),
      ),
    );
  }
}

const _statusText = {
  'not_downloaded': '未下载',
  'downloading': '下载中',
  'failed': '失败，点击重试',
  'cancelled': '已取消',
  'orphaned': '文件丢失',
};

class _Header extends StatelessWidget {
  const _Header({required this.session, required this.author, required this.info});

  final Session session;
  final String author;
  final Blogger? info;

  @override
  Widget build(BuildContext context) {
    final avatar = info?.avatar;
    final stats = <String>[
      if (info != null) '${info!.count} 个视频',
      if (info != null && info!.remote > 0) '${info!.remote} 个未下载',
      if (info?.followers != null) '${formatCount(info!.followers!)} 粉丝',
      if (info != null && info!.platform.isNotEmpty) platformLabel(info!.platform),
    ];
    return Stack(children: [
      Positioned.fill(
        child: avatar == null
            ? const DecoratedBox(decoration: BoxDecoration(gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [Color(0xFF134E4A), Color(0xFF0B1220)])))
            : ImageFiltered(
                imageFilter: ImageFilter.blur(sigmaX: 28, sigmaY: 28),
                child: CachedNetworkImage(imageUrl: session.url(avatar), httpHeaders: session.headers, fit: BoxFit.cover, errorWidget: (_, _, _) => const SizedBox())),
      ),
      const Positioned.fill(child: DecoratedBox(decoration: BoxDecoration(color: Color(0x99000000)))),
      SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.only(bottom: 20),
          child: Column(children: [
            const Align(alignment: Alignment.centerLeft, child: BackBar()),
            const SizedBox(height: 8),
            Avatar(session: session, name: author, path: avatar, size: 88),
            const SizedBox(height: 12),
            Text(author, style: const TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w700)),
            if (info != null && info!.signature.isNotEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(32, 8, 32, 0),
                child: Text(info!.signature, maxLines: 3, overflow: TextOverflow.ellipsis, textAlign: TextAlign.center, style: const TextStyle(color: Colors.white70)),
              ),
            if (stats.isNotEmpty)
              Padding(padding: const EdgeInsets.only(top: 12), child: Text(stats.join('  ·  '), style: const TextStyle(color: Colors.white70, fontSize: 13))),
          ]),
        ),
      ),
    ]);
  }
}
