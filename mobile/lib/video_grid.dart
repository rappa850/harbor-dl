import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import 'api.dart';
import 'widgets.dart';

/// Paged three-column grid of cover images. Tapping one hands the loaded items to [onOpen] so the full-screen feed can
/// start right there and keep paging. Scrolls with the primary controller, so it works inside a NestedScrollView.
class VideoGrid extends StatefulWidget {
  const VideoGrid({super.key, required this.api, required this.mode, required this.emptyText, required this.onOpen, this.author = ''});

  final Api api;
  final String mode, author, emptyText;
  final Future<void> Function(FeedSeed seed) onOpen;

  @override
  State<VideoGrid> createState() => _VideoGridState();
}

class _VideoGridState extends State<VideoGrid> with AutomaticKeepAliveClientMixin {
  final _items = <FeedItem>[];
  String? _next, _error;
  bool _loading = false, _done = false;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _more();
  }

  Future<void> _more() async {
    if (_loading || _done) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final page = await widget.api.feed(cursor: _next, mode: widget.mode, author: widget.author, limit: 30);
      if (!mounted) return;
      setState(() {
        _items.addAll(page.items);
        _next = page.next;
        _done = page.next == null;
      });
    } on Unauthorized {
      // the feed tab notices the expired token on its own; nothing to show here
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _reload() async {
    setState(() {
      _items.clear();
      _next = null;
      _done = false;
    });
    await _more();
  }

  Future<void> _open(int index) async {
    await widget.onOpen(FeedSeed(List.of(_items), _next, index));
    // favorites and history change while watching, so show the current state when the user returns
    if (mounted && (widget.mode == 'favorites' || widget.mode == 'history')) await _reload();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final session = widget.api.session;
    return NotificationListener<ScrollNotification>(
      onNotification: (n) {
        if (n.metrics.extentAfter < 600) _more();
        return false;
      },
      child: CustomScrollView(slivers: [
        if (_items.isEmpty)
          SliverFillRemaining(
            hasScrollBody: false,
            child: Center(
              child: _loading
                  ? const CircularProgressIndicator(strokeWidth: 2)
                  : Column(mainAxisSize: MainAxisSize.min, children: [
                      Text(_error ?? widget.emptyText, style: const TextStyle(color: Colors.white54)),
                      if (_error != null) TextButton(onPressed: _more, child: const Text('重试')),
                    ]),
            ),
          )
        else
          SliverGrid.builder(
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: 3, mainAxisSpacing: 2, crossAxisSpacing: 2, childAspectRatio: 3 / 4),
            itemCount: _items.length,
            itemBuilder: (context, i) {
              final item = _items[i];
              final length = formatDuration(item.duration);
              return GestureDetector(
                onTap: () => _open(i),
                child: Stack(fit: StackFit.expand, children: [
                  ColoredBox(
                    color: Colors.white10,
                    child: item.cover == null
                        ? const SizedBox()
                        : CachedNetworkImage(
                            imageUrl: session.url(item.cover!),
                            httpHeaders: session.headers,
                            fit: BoxFit.cover,
                            memCacheWidth: 360,
                            errorWidget: (_, _, _) => const Icon(Icons.movie_outlined, color: Colors.white24)),
                  ),
                  if (length.isNotEmpty)
                    Positioned(
                        right: 6,
                        bottom: 4,
                        child: Text(length, style: const TextStyle(color: Colors.white, fontSize: 12, shadows: [Shadow(blurRadius: 4)]))),
                  if (item.favorite)
                    const Positioned(left: 6, top: 6, child: Icon(Icons.favorite, size: 16, color: Colors.redAccent)),
                ]),
              );
            },
          ),
        if (_items.isNotEmpty && _loading)
          const SliverToBoxAdapter(child: Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator(strokeWidth: 2)))),
      ]),
    );
  }
}
