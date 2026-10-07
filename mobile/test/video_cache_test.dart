import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:harbor_mobile/api.dart';
import 'package:harbor_mobile/video_cache.dart';

void main() {
  late Directory dir;
  setUp(() => dir = Directory.systemTemp.createTempSync('harbor_cache'));
  tearDown(() => dir.deleteSync(recursive: true));

  FeedItem item(String id) => FeedItem(id, '', '', null, null, '/api/files/$id/stream');
  final session = Session('http://x', 't');

  test('trim drops the least recently written files first', () async {
    final cache = VideoCache(session, dir, limit: 25);
    for (var n = 0; n < 3; n++) {
      File('${dir.path}/v$n.mp4')
        ..writeAsBytesSync(List.filled(10, 0))
        ..setLastModifiedSync(DateTime(2026, 1, 1 + n));
    }
    await cache.trim();
    expect(cache.cached(item('v0')), isNull);
    expect(cache.cached(item('v1')), isNotNull);
    expect(cache.cached(item('v2')), isNotNull);
  });

  test('downloads once, shares concurrent callers and reuses the file', () async {
    var calls = 0;
    final cache = VideoCache(session, dir, downloader: (path, to) async {
      calls++;
      expect(path, '/api/files/c/stream');
      await Future<void>.delayed(const Duration(milliseconds: 20));
      File(to).writeAsBytesSync(List.filled(100, 7));
    });
    final both = await Future.wait([cache.fetch(item('c')), cache.fetch(item('c'))]);
    expect(both.every((f) => f?.lengthSync() == 100), isTrue);
    await cache.fetch(item('c'));
    expect(calls, 1);
    expect(dir.listSync().map((e) => e.path.split(Platform.pathSeparator).last), ['c.mp4']);
  });

  test('failed download leaves nothing behind and returns null', () async {
    final cache = VideoCache(session, dir, downloader: (path, to) async {
      File(to).writeAsBytesSync([1, 2, 3]);
      throw const SocketException('boom');
    });
    expect(await cache.fetch(item('b')), isNull);
    expect(dir.listSync(), isEmpty);
    expect(await cache.fetch(item('b')), isNull); // a failure is not remembered
  });
}
