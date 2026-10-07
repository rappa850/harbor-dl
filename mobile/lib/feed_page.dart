import 'dart:io';

import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import 'api.dart';
import 'feed_tile.dart';
import 'video_cache.dart';

/// How many neighbours on each side keep a prepared (initialised, paused) player.
const kPreload = 1;

/// How many upcoming videos are downloaded to disk ahead of the current page.
const kPrefetch = 2;

/// Watching less than this is not worth a history entry (the user swiped straight past).
const kHistoryAfter = Duration(seconds: 2);

class FeedPage extends StatefulWidget {
  const FeedPage(
      {super.key,
      required this.api,
      required this.onLogout,
      this.mode = 'random',
      this.author = '',
      this.header,
      this.onAuthor,
      this.initial,
      this.active = true});

  final Api api;
  final VoidCallback onLogout;

  /// random | latest | favorites | history (see backend/feed.py)
  final String mode;

  /// Only this author's videos, when set.
  final String author;

  /// Drawn over the top of the feed (mode tabs or a back button).
  final Widget? header;

  /// Opens the author's page. Playback is held until the returned future completes.
  final Future<void> Function(String author)? onAuthor;

  /// Start from items that are already loaded (a tapped grid cell) instead of fetching the first page.
  final FeedSeed? initial;

  /// False while another tab or page covers this feed: playback pauses and resumes with it.
  final bool active;

  @override
  State<FeedPage> createState() => _FeedPageState();
}

class _FeedPageState extends State<FeedPage> with WidgetsBindingObserver {
  late final _pages = PageController(initialPage: widget.initial?.index ?? 0);
  final _items = <FeedItem>[];
  final _players = <int, VideoPlayerController>{};
  final _opening = <int>{};
  VideoCache? _cache;
  String? _next, _error;
  bool _loading = false, _done = false, _paused = false, _fast = false, _held = false;
  late int _index = widget.initial?.index ?? 0;
  late final String _seed = DateTime.now().millisecondsSinceEpoch.toString();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    final initial = widget.initial;
    if (initial != null) {
      _items.addAll(initial.items);
      _next = initial.next;
      _done = initial.next == null;
    }
    _start();
  }

  Future<void> _start() async {
    try {
      _cache = await VideoCache.open(widget.api.session);
    } catch (_) {
      // no usable cache folder: playback still works over the network
    }
    if (!mounted) return;
    if (widget.initial != null) {
      setState(_sync);
    } else {
      _more();
    }
  }

  @override
  void didUpdateWidget(FeedPage old) {
    super.didUpdateWidget(old);
    if (old.active != widget.active) _hold(!widget.active);
  }

  /// Pause while something covers the feed (another tab, the author page); resume afterwards unless the user paused.
  void _hold(bool on) {
    _held = on;
    final player = _players[_index];
    if (on) {
      _report(_index);
      player?.pause();
    } else if (!_paused && player != null && player.value.isInitialized) {
      player.play();
    }
  }

  Future<void> _author(String author) async {
    _hold(true);
    try {
      await widget.onAuthor!(author);
    } finally {
      if (mounted && widget.active) _hold(false);
    }
  }

  @override
  void dispose() {
    _report(_index);
    WidgetsBinding.instance.removeObserver(this);
    for (final player in _players.values) {
      player.dispose();
    }
    _pages.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) {
      _report(_index);
      _players[_index]?.pause();
    } else if (!_paused && !_held) {
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
      final page = await widget.api.feed(cursor: _next, mode: widget.mode, seed: _seed, author: widget.author);
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
    if (current != null && current.value.isInitialized && !_paused && !_held) current.play();
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
    // history resumes where the user stopped, unless that was (almost) the end
    if (widget.mode == 'history' && item.position > 3 && controller.value.duration.inSeconds - item.position > 3) {
      await controller.seekTo(Duration(seconds: item.position.toInt()));
      if (!mounted || _players[i] != controller) return;
    }
    setState(() {});
    if (i == _index && !_paused && !_held) controller.play();
  }

  /// Remember how far the user got in page [i] (fire and forget).
  void _report(int i) {
    final player = _players[i];
    if (player == null || !player.value.isInitialized || i >= _items.length) return;
    final position = player.value.position;
    if (position >= kHistoryAfter) widget.api.watched(_items[i].id, position.inSeconds);
  }

  Future<void> _favorite(FeedItem item, bool on) async {
    if (item.favorite == on) return;
    setState(() => item.favorite = on);
    if (!await widget.api.setFavorite(item.id, on) && mounted) {
      setState(() => item.favorite = !on);
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('操作失败，请检查网络')));
    }
  }

  void _speed(bool fast) {
    _players[_index]?.setPlaybackSpeed(fast ? 2.0 : 1.0);
    setState(() => _fast = fast);
  }

  void _onPage(int index) {
    _report(_index);
    _players[_index]?.setPlaybackSpeed(1.0);
    _index = index;
    _paused = false;
    _fast = false;
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

  String get _emptyText => switch (widget.mode) {
        'favorites' => '还没有收藏，双击视频就能收藏',
        'history' => '还没有观看记录',
        _ => widget.author.isNotEmpty ? '这位作者还没有可播放的视频' : '库里还没有可播放的视频',
      };

  @override
  Widget build(BuildContext context) {
    final header = widget.header;
    if (_items.isEmpty) {
      return Scaffold(
        backgroundColor: Colors.black,
        body: Stack(children: [
          Center(
            child: _loading
                ? const CircularProgressIndicator()
                : Column(mainAxisSize: MainAxisSize.min, children: [
                    Text(_error ?? _emptyText, style: const TextStyle(color: Colors.white70)),
                    const SizedBox(height: 12),
                    FilledButton(onPressed: _more, child: const Text('重试')),
                    TextButton(onPressed: widget.onLogout, child: const Text('切换账号')),
                  ]),
          ),
          // keep the tabs reachable even when this mode has nothing to show
          if (header != null) Positioned(top: 0, left: 0, right: 0, child: SafeArea(child: header)),
        ]),
      );
    }
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(children: [
        PageView.builder(
          controller: _pages,
          scrollDirection: Axis.vertical,
          onPageChanged: _onPage,
          itemCount: _items.length,
          itemBuilder: (context, i) => RepaintBoundary(
            child: VideoTile(
                item: _items[i],
                session: widget.api.session,
                player: _players[i],
                paused: _paused && i == _index,
                fast: _fast && i == _index,
                onToggle: _toggle,
                onFavorite: (on) => _favorite(_items[i], on),
                onSpeed: _speed,
                onAuthor: widget.onAuthor == null || _items[i].author.isEmpty ? null : () => _author(_items[i].author)),
          ),
        ),
        if (header != null) Positioned(top: 0, left: 0, right: 0, child: SafeArea(child: header)),
      ]),
    );
  }
}
