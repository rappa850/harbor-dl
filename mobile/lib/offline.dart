import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:path_provider/path_provider.dart';

import 'api.dart';

/// Videos the user chose to keep on the phone. Unlike [VideoCache] nothing here is trimmed automatically; a copy stays
/// until it is removed. An `index.json` keeps the metadata so the list works without reaching the server.
class Offline {
  Offline(this.dir, {Session? session, Future<void> Function(String path, String to)? downloader}) {
    if (downloader != null) {
      _transfer = downloader;
    } else {
      final dio = Dio(BaseOptions(
          baseUrl: session!.server,
          headers: session.headers,
          connectTimeout: const Duration(seconds: 10),
          receiveTimeout: const Duration(seconds: 30)));
      _transfer = (path, to) => dio.download(path, to);
    }
    _load();
  }

  final Directory dir;
  late final Future<void> Function(String path, String to) _transfer;
  final _entries = <String, FeedItem>{};
  final _inflight = <String, Future<bool>>{};

  static Offline? _shared;

  /// One store per app run, so the feed and the offline tab always see the same list.
  static Future<Offline> open(Session session) async {
    final shared = _shared;
    if (shared != null) return shared;
    final dir = Directory('${(await getApplicationSupportDirectory()).path}/harbor_offline');
    await dir.create(recursive: true);
    return _shared = Offline(dir, session: session);
  }

  /// Drop the shared instance (after logout, so the next login talks to its own server).
  static void forget() => _shared = null;

  File get _index => File('${dir.path}/index.json');
  File video(String id) => File('${dir.path}/$id.mp4');
  File _cover(String id) => File('${dir.path}/$id.jpg');

  void _load() {
    if (!_index.existsSync()) return;
    try {
      for (final raw in jsonDecode(_index.readAsStringSync()) as List) {
        final item = FeedItem.fromJson(raw as Map<String, dynamic>);
        if (video(item.id).existsSync()) _entries[item.id] = _withCover(item);
      }
    } catch (_) {
      // a damaged index only loses the list; the files stay and are overwritten on the next save
    }
  }

  FeedItem _withCover(FeedItem item) => item.withLocalCover(_cover(item.id).existsSync() ? _cover(item.id).path : null);

  void _save() => _index.writeAsStringSync(jsonEncode([for (final item in _entries.values) item.toJson()]));

  bool has(String id) => _entries.containsKey(id);

  /// The saved copy of [id], when there is one.
  File? file(String id) => has(id) ? video(id) : null;

  /// Newest download first.
  List<FeedItem> items() => _entries.values.toList().reversed.toList();

  /// True once [item] is on the device (immediately when it already was). A failed transfer leaves nothing behind.
  Future<bool> add(FeedItem item) {
    if (has(item.id)) return Future.value(true);
    return _inflight.putIfAbsent(item.id, () => _download(item).whenComplete(() {
          _inflight.remove(item.id); // block body, see VideoCache.fetch
        }));
  }

  bool downloading(String id) => _inflight.containsKey(id);

  Future<bool> _download(FeedItem item) async {
    final target = video(item.id), part = File('${target.path}.part');
    try {
      await _transfer(item.stream, part.path);
      await part.rename(target.path);
    } catch (_) {
      if (part.existsSync()) part.deleteSync();
      return false;
    }
    if (item.cover != null) {
      try {
        await _transfer(item.cover!, _cover(item.id).path);
      } catch (_) {
        if (_cover(item.id).existsSync()) _cover(item.id).deleteSync();
      }
    }
    _entries[item.id] = _withCover(item);
    _save();
    return true;
  }

  void remove(String id) {
    _entries.remove(id);
    for (final file in [video(id), _cover(id)]) {
      if (file.existsSync()) file.deleteSync();
    }
    _save();
  }

  void clear() {
    for (final id in _entries.keys.toList()) {
      remove(id);
    }
  }

  /// Bytes taken by the saved videos and covers.
  int size() => dir.existsSync() ? dir.listSync().whereType<File>().where((f) => !f.path.endsWith('index.json')).fold(0, (sum, f) => sum + f.lengthSync()) : 0;
}
