import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import 'api.dart';
import 'console_api.dart';
import 'console_models.dart';
import 'widgets.dart';

/// A picture post: swipe through the pictures (pinch to zoom), background music plays and can be muted.
class GalleryPage extends StatefulWidget {
  const GalleryPage({super.key, required this.api, required this.assetId, required this.title, required this.onLogout});

  final Api api;
  final String assetId, title;
  final VoidCallback onLogout;

  @override
  State<GalleryPage> createState() => _GalleryPageState();
}

class _GalleryPageState extends State<GalleryPage> {
  Gallery? _gallery;
  String? _error;
  PageController? _pages;
  int _page = 0;
  VideoPlayerController? _music;
  bool _muted = false;

  Api get _api => widget.api;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _pages?.dispose();
    _music?.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final gallery = await _api.gallery(widget.assetId);
      if (!mounted) return;
      setState(() {
        _gallery = gallery;
        _page = gallery.index.clamp(0, gallery.images.isEmpty ? 0 : gallery.images.length - 1);
        _pages = PageController(initialPage: _page);
      });
      _openMusic(gallery);
    } on Unauthorized {
      await Session.clear();
      widget.onLogout();
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  Future<void> _openMusic(Gallery gallery) async {
    final id = gallery.audio;
    if (id == null) return;
    final controller = VideoPlayerController.networkUrl(Uri.parse(_api.session.url('/api/files/$id/stream')),
        httpHeaders: _api.session.headers, videoPlayerOptions: VideoPlayerOptions(mixWithOthers: false));
    try {
      await controller.initialize();
      await controller.setLooping(true);
      if (!mounted) {
        await controller.dispose();
        return;
      }
      setState(() => _music = controller);
      await controller.play();
    } catch (_) {
      await controller.dispose(); // music is a bonus; the pictures still show
    }
  }

  void _toggleMusic() {
    final music = _music;
    if (music == null) return;
    setState(() => _muted = !_muted);
    _muted ? music.pause() : music.play();
  }

  @override
  Widget build(BuildContext context) {
    final gallery = _gallery;
    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: Stack(children: [
          if (gallery == null)
            Center(child: _error == null ? const CircularProgressIndicator() : Text(_error!, style: const TextStyle(color: Colors.white70)))
          else if (gallery.images.isEmpty)
            const Center(child: Text('没有可显示的图片', style: TextStyle(color: Colors.white54)))
          else
            PageView.builder(
              controller: _pages,
              itemCount: gallery.images.length,
              onPageChanged: (i) => setState(() => _page = i),
              itemBuilder: (_, i) => InteractiveViewer(
                maxScale: 5,
                child: CachedNetworkImage(
                    imageUrl: _api.session.url('/api/files/${gallery.images[i]}/stream'),
                    httpHeaders: _api.session.headers,
                    fit: BoxFit.contain,
                    placeholder: (_, _) => const Center(child: CircularProgressIndicator()),
                    errorWidget: (_, _, _) => const Center(child: Icon(Icons.broken_image, color: Colors.white38, size: 48))),
              ),
            ),
          Positioned(top: 0, left: 0, right: 0, child: Row(children: [
            Expanded(child: BackBar(title: widget.title)),
            if (_music != null) IconButton(onPressed: _toggleMusic, icon: Icon(_muted ? Icons.music_off : Icons.music_note, color: Colors.white)),
          ])),
          if (gallery != null && gallery.images.length > 1)
            Positioned(
                bottom: 16,
                left: 0,
                right: 0,
                child: Center(child: Text('${_page + 1} / ${gallery.images.length}', style: const TextStyle(color: Colors.white70)))),
        ]),
      ),
    );
  }
}
