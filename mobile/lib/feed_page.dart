import 'dart:io';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:video_player/video_player.dart';

import 'api.dart';
import 'video_cache.dart';

/// How many neighbours on each side keep a prepared (initialised, paused) player.
const kPreload = 1;

/// How many upcoming videos are downloaded to disk ahead of the current page.
const kPrefetch = 2;

class FeedPage extends StatefulWidget {
  const FeedPage({super.key, required this.api, required this.onLogout});

  final Api api;
  final VoidCallback onLogout;

  @override
  State<FeedPage> createState() => _FeedPageState();
}

class _FeedPageState extends State<FeedPage> with WidgetsBindingObserver {
  final _pages = PageController();
  final _items = <FeedItem>[];
  final _players = <int, VideoPlayerController>{};
  final _opening = <int>{};
  VideoCache? _cache;
  String? _next, _error;
  bool _loading = false, _done = false, _paused = false;
  int _index = 0;
  late final String _seed = DateTime.now().millisecondsSinceEpoch.toString();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
    _start();
  }

  Future<void> _start() async {
    try {
      _cache = await VideoCache.open(widget.api.session);
    } catch (_) {
      // no usable cache folder: playback still works over the network
    }
    if (mounted) _more();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
    for (final player in _players.values) {
      player.dispose();
    }
    _pages.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) {
      _players[_index]?.pause();
    } else if (!_paused) {
      _players[_index]?.play();
    }
  }

  Future<void> _more() async {
    if (_loading || _done) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final page = await widget.api.feed(cursor: _next, mode: 'random', seed: _seed);
      if (!mounted) return;
      setState(() {
        _items.addAll(page.items);
        _next = page.next;
        _done = page.next == null;
      });
      _sync();
    } on Unauthorized {
      await Session.clear();
      widget.onLogout();
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Keep exactly the current page and its neighbours prepared; release everything else.
  void _sync() {
    if (_items.isEmpty) return;
    final wanted = {for (var i = _index - kPreload; i <= _index + kPreload; i++) if (i >= 0 && i < _items.length) i};
    for (final i in _players.keys.where((i) => !wanted.contains(i)).toList()) {
      _players.remove(i)!.dispose();
    }
    for (final i in wanted) {
      if (_players.containsKey(i)) {
        if (i != _index) _players[i]!.pause();
      } else if (_opening.add(i)) {
        _open(i);
      }
    }
    for (var k = 1; k <= kPrefetch && _index + k < _items.length; k++) {
      _cache?.fetch(_items[_index + k]);
    }
    final current = _players[_index];
    if (current != null && current.value.isInitialized && !_paused) current.play();
  }

  /// Start a player for page [i]: from disk when the file is already local, otherwise from the network. A neighbour
  /// page waits briefly for its prefetch so it does not download the same bytes twice; the current page never waits.
  Future<void> _open(int i) async {
    final item = _items[i];
    File? file = _cache?.cached(item);
    if (file == null && i != _index && _cache != null) {
      file = await _cache!.fetch(item).timeout(const Duration(seconds: 8), onTimeout: () => null);
    }
    _opening.remove(i);
    if (!mounted || _players.containsKey(i) || (i - _index).abs() > kPreload) return;
    final options = VideoPlayerOptions(mixWithOthers: false);
    final controller = file != null
        ? VideoPlayerController.file(file, videoPlayerOptions: options)
        : VideoPlayerController.networkUrl(Uri.parse(widget.api.session.url(item.stream)),
            httpHeaders: widget.api.session.headers, videoPlayerOptions: options);
    _players[i] = controller;
    controller.setLooping(true);
    try {
      await controller.initialize();
    } catch (_) {
      if (mounted) setState(() {});
      return;
    }
    if (!mounted || _players[i] != controller) return;
    setState(() {});
    if (i == _index && !_paused) controller.play();
  }

  void _onPage(int index) {
    _index = index;
    _paused = false;
    _sync();
    if (index >= _items.length - 5) _more();
  }

  void _toggle() {
    final player = _players[_index];
    if (player == null || !player.value.isInitialized) return;
    setState(() {
      _paused = player.value.isPlaying;
      _paused ? player.pause() : player.play();
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_items.isEmpty) {
      return Scaffold(
        backgroundColor: Colors.black,
        body: Center(
          child: _loading
              ? const CircularProgressIndicator()
              : Column(mainAxisSize: MainAxisSize.min, children: [
                  Text(_error ?? '库里还没有可播放的视频', style: const TextStyle(color: Colors.white70)),
                  const SizedBox(height: 12),
                  FilledButton(onPressed: _more, child: const Text('重试')),
                  TextButton(onPressed: widget.onLogout, child: const Text('切换账号')),
                ]),
        ),
      );
    }
    return Scaffold(
      backgroundColor: Colors.black,
      body: PageView.builder(
        controller: _pages,
        scrollDirection: Axis.vertical,
        onPageChanged: _onPage,
        itemCount: _items.length,
        itemBuilder: (context, i) => RepaintBoundary(
          child: _VideoTile(
              item: _items[i],
              session: widget.api.session,
              player: _players[i],
              paused: _paused && i == _index,
              onTap: _toggle),
        ),
      ),
    );
  }
}

class _VideoTile extends StatelessWidget {
  const _VideoTile({required this.item, required this.session, required this.player, required this.paused, required this.onTap});

  final FeedItem item;
  final Session session;
  final VideoPlayerController? player;
  final bool paused;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final controller = player;
    final ready = controller != null && controller.value.isInitialized;
    final failed = controller?.value.hasError ?? false;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      child: Stack(fit: StackFit.expand, children: [
        // the cover stays underneath until the first frame is ready, so a swipe never shows black
        if (item.cover != null)
          CachedNetworkImage(
              imageUrl: session.url(item.cover!), httpHeaders: session.headers, fit: BoxFit.contain, errorWidget: (_, _, _) => const SizedBox()),
        if (ready)
          Center(
              child: AspectRatio(
                  aspectRatio: controller.value.aspectRatio, child: VideoPlayer(controller))),
        if (!ready && !failed) const Center(child: CircularProgressIndicator(strokeWidth: 2)),
        if (failed) const Center(child: Text('无法播放这个视频', style: TextStyle(color: Colors.white70))),
        if (paused) const Center(child: Icon(Icons.play_arrow_rounded, size: 88, color: Colors.white70)),
        Positioned(
          left: 16,
          right: 16,
          bottom: 24,
          child: SafeArea(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              if (item.author.isNotEmpty)
                Text('@${item.author}', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 16)),
              const SizedBox(height: 6),
              Text(item.title, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white, fontSize: 14)),
            ]),
          ),
        ),
        if (ready)
          Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              child: VideoProgressIndicator(controller, allowScrubbing: false, padding: EdgeInsets.zero,
                  colors: const VideoProgressColors(playedColor: Colors.white, bufferedColor: Colors.white24, backgroundColor: Colors.transparent))),
      ]),
    );
  }
}
