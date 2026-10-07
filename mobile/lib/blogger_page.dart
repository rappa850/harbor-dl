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

  @override
  void initState() {
    super.initState();
    _load();
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
          emptyText: '这位博主还没有可播放的视频',
          onOpen: (seed) => openFeed(context, api: widget.api, onLogout: widget.onLogout, seed: seed, mode: 'latest', author: widget.author),
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.session, required this.author, required this.info});

  final Session session;
  final String author;
  final Blogger? info;

  @override
  Widget build(BuildContext context) {
    final avatar = info?.avatar;
    final stats = <String>[
      if (info != null) '${info!.count} 个作品',
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
