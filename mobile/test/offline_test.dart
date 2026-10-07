import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:harbor_mobile/api.dart';
import 'package:harbor_mobile/offline.dart';
import 'package:harbor_mobile/settings.dart';
import 'package:harbor_mobile/video_cache.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  late Directory dir;
  setUp(() => dir = Directory.systemTemp.createTempSync('harbor_offline'));
  tearDown(() => dir.deleteSync(recursive: true));

  FeedItem item(String id, {String? cover = '/api/covers/k'}) =>
      FeedItem(id, 'title $id', 'author', 12, cover, '/api/files/$id/stream');
  final session = Session('http://x', 't');

  Future<void> fake(String path, String to) async => File(to).writeAsBytesSync(List.filled(path.length, 1));

  test('saves a video with its cover and lists it newest first', () async {
    final offline = Offline(dir, downloader: fake);
    expect(await offline.add(item('a')), isTrue);
    expect(await offline.add(item('b')), isTrue);
    expect(offline.items().map((i) => i.id), ['b', 'a']);
    expect(offline.items().first.localCover, endsWith('b.jpg'));
    expect(offline.file('a'), isNotNull);
    expect(offline.size(), greaterThan(0));
  });

  test('the list survives a restart and drops entries whose file vanished', () async {
    await Offline(dir, downloader: fake).add(item('a'));
    await Offline(dir, downloader: fake).add(item('b'));
    File('${dir.path}/a.mp4').deleteSync();
    final again = Offline(dir, downloader: fake);
    expect(again.items().map((i) => i.id), ['b']);
    expect(again.has('a'), isFalse);
  });

  test('a failed transfer leaves nothing and can be retried', () async {
    var fail = true;
    final offline = Offline(dir, downloader: (path, to) async {
      File(to).writeAsBytesSync([1]);
      if (fail) throw const SocketException('boom');
    });
    expect(await offline.add(item('x')), isFalse);
    expect(dir.listSync(), isEmpty);
    fail = false;
    expect(await offline.add(item('x')), isTrue);
  });

  test('a missing cover does not fail the video', () async {
    final offline = Offline(dir, downloader: (path, to) async {
      if (path.contains('covers')) throw const SocketException('no cover');
      File(to).writeAsBytesSync([1]);
    });
    expect(await offline.add(item('v')), isTrue);
    expect(offline.items().single.localCover, isNull);
  });

  test('remove and clear delete the files', () async {
    final offline = Offline(dir, downloader: fake);
    await offline.add(item('a'));
    await offline.add(item('b'));
    offline.remove('a');
    expect(offline.has('a'), isFalse);
    expect(File('${dir.path}/a.mp4').existsSync(), isFalse);
    offline.clear();
    expect(offline.items(), isEmpty);
    expect(offline.size(), 0);
  });

  test('concurrent adds share one transfer', () async {
    var calls = 0;
    final offline = Offline(dir, downloader: (path, to) async {
      calls++;
      await Future<void>.delayed(const Duration(milliseconds: 10));
      File(to).writeAsBytesSync([1]);
    });
    final first = offline.add(item('c', cover: null)), second = offline.add(item('c', cover: null));
    expect(offline.downloading('c'), isTrue);
    expect(await Future.wait([first, second]), [true, true]);
    expect(calls, 1);
  });

  group('video cache', () {
    late Directory cacheDir;
    setUp(() => cacheDir = Directory.systemTemp.createTempSync('harbor_vc'));
    tearDown(() => cacheDir.deleteSync(recursive: true));

    test('a saved copy wins over the network and counts as cached', () async {
      final offline = Offline(dir, downloader: fake);
      await offline.add(item('s'));
      final cache = VideoCache(session, cacheDir, offline: offline, downloader: (p, t) async => fail('must not download'));
      expect(cache.cached(item('s'))?.path, offline.video('s').path);
      expect((await cache.fetch(item('s')))?.path, offline.video('s').path);
    });

    test('prefetch is skipped when not allowed, but a cached file is still returned', () async {
      var downloads = 0;
      var allowed = false;
      final cache = VideoCache(session, cacheDir, prefetchAllowed: () async => allowed, downloader: (path, to) async {
        downloads++;
        File(to).writeAsBytesSync([1]);
      });
      expect(await cache.prefetch(item('p')), isNull);
      expect(downloads, 0);
      allowed = true;
      expect(await cache.prefetch(item('p')), isNotNull);
      allowed = false;
      expect(await cache.prefetch(item('p')), isNotNull);
      expect(downloads, 1);
    });
  });

  test('settings default to Wi-Fi only prefetch and 1 GB, and persist changes', () async {
    SharedPreferences.setMockInitialValues({});
    final settings = await AppSettings.load();
    expect((settings.wifiOnlyPrefetch, settings.cacheMb, settings.cacheBytes), (true, 1024, 1024 * 1024 * 1024));
    await settings.setWifiOnlyPrefetch(false);
    await settings.setCacheMb(2048);
    final again = await AppSettings.load();
    expect((again.wifiOnlyPrefetch, again.cacheMb), (false, 2048));
  });
}
