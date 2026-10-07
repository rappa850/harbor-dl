import 'dart:io';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import 'api.dart';

/// One full-screen page of the feed: cover, video, overlay text, actions and the touch gestures.
class VideoTile extends StatefulWidget {
  const VideoTile(
      {super.key,
      required this.item,
      required this.session,
      required this.player,
      required this.paused,
      required this.fast,
      required this.onToggle,
      required this.onFavorite,
      required this.onSpeed,
      required this.onAuthor,
      this.saved = false,
      this.saving = false,
      this.onSave,
      this.loop = false,
      this.onLoop,
      this.bare = false,
      this.onPip});

  final FeedItem item;
  final Session session;
  final VideoPlayerController? player;
  final bool paused, fast;
  final VoidCallback onToggle;
  final void Function(bool on) onFavorite;
  final void Function(bool fast) onSpeed;
  final VoidCallback? onAuthor;

  /// Offline copy state; [onSave] toggles it (null hides the button).
  final bool saved, saving;
  final VoidCallback? onSave;

  /// Only the picture, for the picture-in-picture window; [onPip] shrinks the app into it (null hides the button).
  final bool bare;

  /// Single-video loop (true) or automatic continuation (false); [onLoop] switches between them.
  final bool loop;
  final VoidCallback? onLoop;
  final VoidCallback? onPip;

  @override
  State<VideoTile> createState() => _VideoTileState();
}

class _VideoTileState extends State<VideoTile> {
  static const _doubleTap = Duration(milliseconds: 280);
  DateTime _lastTap = DateTime.fromMillisecondsSinceEpoch(0);
  Offset? _burst;
  int _bursts = 0;

  /// A single tap pauses at once (no waiting to see whether a second one follows); a quick second tap undoes that
  /// toggle by toggling again and likes instead.
  void _tap(TapUpDetails details) {
    final now = DateTime.now();
    widget.onToggle();
    if (now.difference(_lastTap) < _doubleTap) {
      _lastTap = DateTime.fromMillisecondsSinceEpoch(0);
      widget.onFavorite(true);
      setState(() {
        _burst = details.localPosition;
        _bursts++;
      });
    } else {
      _lastTap = now;
    }
  }

  @override
  Widget build(BuildContext context) {
    final item = widget.item, session = widget.session, controller = widget.player;
    final ready = controller != null && controller.value.isInitialized;
    final failed = controller?.value.hasError ?? false;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTapUp: _tap,
      onLongPressStart: (_) => widget.onSpeed(true),
      onLongPressEnd: (_) => widget.onSpeed(false),
      child: Stack(fit: StackFit.expand, children: [
        // the cover stays underneath until the first frame is ready, so a swipe never shows black
        if (item.localCover != null)
          Image.file(File(item.localCover!), fit: BoxFit.contain, errorBuilder: (_, _, _) => const SizedBox())
        else if (item.cover != null)
          CachedNetworkImage(
              imageUrl: session.url(item.cover!),
              httpHeaders: session.headers,
              fit: BoxFit.contain,
              errorWidget: (_, _, _) => const SizedBox()),
        if (ready) Center(child: AspectRatio(aspectRatio: controller.value.aspectRatio, child: VideoPlayer(controller))),
        if (!ready && !failed) const Center(child: CircularProgressIndicator(strokeWidth: 2)),
        if (failed) const Center(child: Text('无法播放这个视频', style: TextStyle(color: Colors.white70))),
        if (widget.paused) const Center(child: Icon(Icons.play_arrow_rounded, size: 88, color: Colors.white70)),
        if (widget.fast)
          const Positioned(
              top: 96,
              left: 0,
              right: 0,
              child: Center(child: Text('2× 快进中', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w600)))),
        if (_burst != null)
          Positioned(
            left: _burst!.dx - 48,
            top: _burst!.dy - 48,
            child: IgnorePointer(
              child: TweenAnimationBuilder<double>(
                key: ValueKey(_bursts),
                tween: Tween(begin: 0, end: 1),
                duration: const Duration(milliseconds: 650),
                builder: (_, t, _) => Opacity(
                    opacity: (1 - t).clamp(0.0, 1.0),
                    child: Transform.scale(
                        scale: 0.6 + 0.9 * Curves.easeOutBack.transform(t),
                        child: const Icon(Icons.favorite, size: 96, color: Colors.redAccent))),
              ),
            ),
          ),
        if (!widget.bare)
        Positioned(
          left: 16,
          right: 88,
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
        if (!widget.bare)
        Positioned(
          right: 8,
          bottom: 48,
          child: SafeArea(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              IconButton(
                iconSize: 36,
                tooltip: item.favorite ? '取消收藏' : '收藏',
                onPressed: () => widget.onFavorite(!item.favorite),
                icon: Icon(item.favorite ? Icons.favorite : Icons.favorite_border, color: item.favorite ? Colors.redAccent : Colors.white),
              ),
              if (widget.onSave != null)
                IconButton(
                    iconSize: 32,
                    tooltip: widget.saved ? '删除离线副本' : '保存到手机',
                    onPressed: widget.saving ? null : widget.onSave,
                    icon: widget.saving
                        ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2))
                        : Icon(widget.saved ? Icons.download_done : Icons.download_outlined, color: widget.saved ? Colors.lightGreenAccent : Colors.white)),
              if (widget.onLoop != null)
                IconButton(
                    iconSize: 30,
                    tooltip: widget.loop ? '单曲循环（点击切换为自动连播）' : '自动连播（点击切换为单曲循环）',
                    onPressed: widget.onLoop,
                    icon: Icon(widget.loop ? Icons.repeat_one : Icons.playlist_play, color: widget.loop ? Colors.amberAccent : Colors.white)),
              if (widget.onPip != null)
                IconButton(
                    iconSize: 30,
                    tooltip: '小窗播放',
                    onPressed: widget.onPip,
                    icon: const Icon(Icons.picture_in_picture_alt_outlined, color: Colors.white)),
              if (widget.onAuthor != null)
                IconButton(
                    iconSize: 32,
                    tooltip: '这位作者的视频',
                    onPressed: widget.onAuthor,
                    icon: const Icon(Icons.account_circle_outlined, color: Colors.white)),
            ]),
          ),
        ),
        if (ready && !widget.bare)
          Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              child: VideoProgressIndicator(controller,
                  allowScrubbing: true,
                  padding: const EdgeInsets.symmetric(vertical: 10),
                  colors: const VideoProgressColors(playedColor: Colors.white, bufferedColor: Colors.white24, backgroundColor: Colors.transparent))),
      ]),
    );
  }
}
