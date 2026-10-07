import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import 'api.dart';
import 'offline.dart';
import 'offline_tab.dart';
import 'settings.dart';
import 'video_cache.dart';
import 'video_grid.dart';
import 'widgets.dart';

/// The user's own page: avatar and background picture (both changeable), counts, favorites and history as grids.
class MePage extends StatefulWidget {
  const MePage({super.key, required this.api, required this.onLogout});

  final Api api;
  final VoidCallback onLogout;

  @override
  State<MePage> createState() => _MePageState();
}

class _MePageState extends State<MePage> with SingleTickerProviderStateMixin {
  late final _tabs = TabController(length: 3, vsync: this);
  Me? _me;
  bool _busy = false;

  Api get _api => widget.api;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final me = await _api.me();
      if (mounted) setState(() => _me = me);
    } on Unauthorized {
      await Session.clear();
      widget.onLogout();
    } catch (_) {
      // keep showing what is there; the pull of a new tab visit retries
    }
  }

  void _say(String text) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));

  Future<void> _change(String kind) async {
    final avatar = kind == 'avatar';
    final file = await ImagePicker().pickImage(source: ImageSource.gallery, maxWidth: avatar ? 512 : 1440, imageQuality: 88);
    if (file == null) return;
    setState(() => _busy = true);
    try {
      await _api.putPicture(kind, await file.readAsBytes());
      await _load();
    } on Unauthorized {
      await Session.clear();
      widget.onLogout();
    } catch (e) {
      if (mounted) _say('$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _remove(String kind) async {
    try {
      await _api.deletePicture(kind);
      await _load();
    } catch (e) {
      if (mounted) _say('$e');
    }
  }

  Future<void> _pictureMenu(String kind) {
    final avatar = kind == 'avatar';
    final has = avatar ? _me?.avatar != null : _me?.background != null;
    return showModalBottomSheet<void>(
      context: context,
      builder: (sheet) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
              leading: const Icon(Icons.photo_library_outlined),
              title: Text(avatar ? '更换头像' : '更换主页背景'),
              onTap: () {
                Navigator.pop(sheet);
                _change(kind);
              }),
          if (has)
            ListTile(
                leading: const Icon(Icons.delete_outline),
                title: Text(avatar ? '移除头像' : '移除背景'),
                onTap: () {
                  Navigator.pop(sheet);
                  _remove(kind);
                }),
        ]),
      ),
    );
  }

  Future<void> _settings() async {
    final cache = await VideoCache.open(_api.session), settings = await AppSettings.load();
    if (!mounted) return;
    await showModalBottomSheet<void>(
      context: context,
      builder: (sheet) => StatefulBuilder(
        builder: (context, setSheet) => SafeArea(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            ListTile(leading: const Icon(Icons.dns_outlined), title: const Text('服务器'), subtitle: Text(_api.session.server)),
            SwitchListTile(
                secondary: const Icon(Icons.wifi),
                title: const Text('仅 Wi-Fi 下预加载'),
                subtitle: const Text('移动网络只播放当前视频，不提前下载后面的'),
                value: settings.wifiOnlyPrefetch,
                onChanged: (on) async {
                  await settings.setWifiOnlyPrefetch(on);
                  setSheet(() {});
                }),
            ListTile(
                leading: const Icon(Icons.storage_outlined),
                title: const Text('缓存上限'),
                trailing: DropdownButton<int>(
                    value: kCacheChoices.contains(settings.cacheMb) ? settings.cacheMb : 1024,
                    underline: const SizedBox(),
                    items: [for (final mb in kCacheChoices) DropdownMenuItem(value: mb, child: Text(mb >= 1024 ? '${mb ~/ 1024} GB' : '$mb MB'))],
                    onChanged: (mb) async {
                      if (mb == null) return;
                      await settings.setCacheMb(mb);
                      await VideoCache(_api.session, cache.dir, limit: settings.cacheBytes).trim();
                      setSheet(() {});
                    })),
            ListTile(
                leading: const Icon(Icons.cleaning_services_outlined),
                title: const Text('清除视频缓存'),
                subtitle: Text('已占用 ${(cache.size() / (1024 * 1024)).toStringAsFixed(1)} MB'),
                onTap: () {
                  cache.clear();
                  setSheet(() {});
                }),
            ListTile(
                leading: const Icon(Icons.logout),
                title: const Text('退出登录'),
                onTap: () async {
                  Navigator.pop(sheet);
                  await Session.clear();
                  Offline.forget();
                  widget.onLogout();
                }),
          ]),
        ),
      ),
    );
  }

  Widget _stat(String label, int? value, {VoidCallback? onTap}) => Expanded(
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Column(children: [
              Text(value == null ? '–' : '$value', style: const TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w700)),
              Text(label, style: const TextStyle(color: Colors.white70, fontSize: 12)),
            ]),
          ),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final me = _me, session = _api.session;
    final name = me?.username ?? '';
    return Scaffold(
      backgroundColor: Colors.black,
      body: NestedScrollView(
        headerSliverBuilder: (context, _) => [
          SliverToBoxAdapter(
            child: Stack(children: [
              Positioned.fill(
                child: GestureDetector(
                  onTap: () => _pictureMenu('background'),
                  child: me?.background == null
                      ? const DecoratedBox(decoration: BoxDecoration(gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [Color(0xFF134E4A), Color(0xFF0B1220)])))
                      : CachedNetworkImage(
                          imageUrl: session.url('/api/auth/background?v=${me!.background}'),
                          httpHeaders: session.headers,
                          fit: BoxFit.cover,
                          errorWidget: (_, _, _) => const SizedBox()),
                ),
              ),
              const Positioned.fill(
                  child: IgnorePointer(
                      child: DecoratedBox(
                          decoration: BoxDecoration(gradient: LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: [Color(0x33000000), Color(0xCC000000)]))))),
              SafeArea(
                bottom: false,
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Column(children: [
                    Align(alignment: Alignment.centerRight, child: IconButton(onPressed: _settings, icon: const Icon(Icons.settings_outlined, color: Colors.white))),
                    const SizedBox(height: 40),
                    GestureDetector(
                      onTap: () => _pictureMenu('avatar'),
                      child: Stack(alignment: Alignment.bottomRight, children: [
                        Avatar(session: session, name: name, path: me?.avatar == null ? null : '/api/auth/avatar?v=${me!.avatar}', size: 92),
                        const CircleAvatar(radius: 14, backgroundColor: Colors.black87, child: Icon(Icons.camera_alt, size: 16, color: Colors.white)),
                      ]),
                    ),
                    const SizedBox(height: 10),
                    Text(name, style: const TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w700)),
                    if (_busy) const Padding(padding: EdgeInsets.only(top: 6), child: Text('上传中…', style: TextStyle(color: Colors.white70, fontSize: 12))),
                    const SizedBox(height: 8),
                    Row(children: [
                      _stat('视频', me?.videos),
                      _stat('收藏', me?.favorites, onTap: () => _tabs.animateTo(0)),
                      _stat('历史', me?.history, onTap: () => _tabs.animateTo(1)),
                    ]),
                  ]),
                ),
              ),
            ]),
          ),
          SliverPersistentHeader(pinned: true, delegate: _TabBarDelegate(TabBar(controller: _tabs, tabs: const [Tab(text: '收藏'), Tab(text: '观看历史'), Tab(text: '离线')]))),
        ],
        body: TabBarView(controller: _tabs, children: [
          VideoGrid(
            api: _api,
            mode: 'favorites',
            emptyText: '还没有收藏，双击视频就能收藏',
            onOpen: (seed) async {
              await openFeed(context, api: _api, onLogout: widget.onLogout, seed: seed, mode: 'favorites');
              _load();
            },
          ),
          VideoGrid(
            api: _api,
            mode: 'history',
            emptyText: '还没有观看记录',
            onOpen: (seed) async {
              await openFeed(context, api: _api, onLogout: widget.onLogout, seed: seed, mode: 'history');
              _load();
            },
          ),
          OfflineTab(api: _api, onLogout: widget.onLogout),
        ]),
      ),
    );
  }
}

class _TabBarDelegate extends SliverPersistentHeaderDelegate {
  _TabBarDelegate(this.bar);

  final TabBar bar;

  @override
  double get minExtent => bar.preferredSize.height;
  @override
  double get maxExtent => bar.preferredSize.height;

  @override
  Widget build(BuildContext context, double shrinkOffset, bool overlapsContent) => ColoredBox(color: Colors.black, child: bar);

  @override
  bool shouldRebuild(_TabBarDelegate old) => old.bar != bar;
}
