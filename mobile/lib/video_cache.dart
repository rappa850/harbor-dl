import 'dart:io';

import 'package:dio/dio.dart';
import 'package:path_provider/path_provider.dart';

import 'api.dart';
import 'offline.dart';
import 'settings.dart';

/// Whole-file disk cache for upcoming videos. A file that is already local starts instantly and costs no traffic
/// when the same video is shown again. Least recently written files are dropped once the folder exceeds [limit].
class VideoCache {
  VideoCache(this.session, this.dir,
      {this.limit = 1 << 30, this.offline, this.prefetchAllowed, Future<void> Function(String path, String to)? downloader})
      : _dio = Dio(BaseOptions(
            baseUrl: session.server,
            headers: session.headers,
            connectTimeout: const Duration(seconds: 10),
            receiveTimeout: const Duration(seconds: 30))) {
    _transfer = downloader ?? (path, to) => _dio.download(path, to);
  }

  final Session session;
  final Directory dir;
  final int limit;

  /// Copies the user saved on purpose; they win over the cache and are never trimmed.
  final Offline? offline;

  /// Asked before every prefetch (Wi-Fi only setting); null means always.
  final Future<bool> Function()? prefetchAllowed;
  final Dio _dio;
  late final Future<void> Function(String path, String to) _transfer;
  final _inflight = <String, Future<File?>>{};

  static Future<VideoCache> open(Session session) async {
    final settings = await AppSettings.load(), offline = await Offline.open(session);
    final dir = Directory('${(await getTemporaryDirectory()).path}/harbor_videos');
    await dir.create(recursive: true);
    // half-finished downloads from an earlier run are never reused
    for (final entry in dir.listSync().whereType<File>().where((f) => f.path.endsWith('.part'))) {
      entry.deleteSync();
    }
    return VideoCache(session, dir,
        limit: settings.cacheBytes,
        offline: offline,
        prefetchAllowed: () async => !settings.wifiOnlyPrefetch || await onUnmeteredNetwork());
  }

  File _file(FeedItem item) => File('${dir.path}/${item.id}.mp4');

  File? cached(FeedItem item) {
    final saved = offline?.file(item.id);
    if (saved != null) return saved;
    final file = _file(item);
    return file.existsSync() ? file : null;
  }

  /// Warm the cache for a video that is likely to be watched next; skipped on metered networks when the user asked.
  Future<File?> prefetch(FeedItem item) async {
    final hit = cached(item);
    if (hit != null) return hit;
    if (prefetchAllowed != null && !await prefetchAllowed!()) return null;
    return fetch(item);
  }

  /// Download [item] once (concurrent callers share the same transfer). Null when it could not be fetched.
  Future<File?> fetch(FeedItem item) {
    final hit = cached(item);
    if (hit != null) return Future.value(hit);
    return _inflight.putIfAbsent(item.id, () => _download(item).whenComplete(() {
          _inflight.remove(item.id); // block body: an arrow would return the future being completed and deadlock
        }));
  }

  Future<File?> _download(FeedItem item) async {
    final target = _file(item), part = File('${target.path}.part');
    try {
      await _transfer(item.stream, part.path);
      await part.rename(target.path);
    } catch (_) {
      if (part.existsSync()) part.deleteSync();
      return null;
    }
    await trim();
    return target;
  }

  /// Bytes the cached videos occupy.
  int size() => dir.existsSync() ? dir.listSync().whereType<File>().fold(0, (sum, f) => sum + f.lengthSync()) : 0;

  void clear() {
    if (!dir.existsSync()) return;
    for (final file in dir.listSync().whereType<File>()) {
      file.deleteSync();
    }
  }

  Future<void> trim() async {
    final files = dir.listSync().whereType<File>().where((f) => f.path.endsWith('.mp4')).toList();
    final stats = {for (final f in files) f: f.statSync()};
    var total = stats.values.fold<int>(0, (sum, s) => sum + s.size);
    files.sort((a, b) => stats[a]!.modified.compareTo(stats[b]!.modified));
    for (final file in files) {
      if (total <= limit) break;
      total -= stats[file]!.size;
      file.deleteSync();
    }
  }
}
