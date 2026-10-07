import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harbor_mobile/api.dart';
import 'package:harbor_mobile/login_page.dart';
import 'package:harbor_mobile/blogger_page.dart';
import 'package:harbor_mobile/widgets.dart';

void main() {
  test('normalizeServer adds scheme and trims slashes', () {
    expect(normalizeServer(' 192.168.1.10:8765/ '), 'http://192.168.1.10:8765');
    expect(normalizeServer('https://nas.example.com//'), 'https://nas.example.com');
  });

  test('FeedItem parses a feed row', () {
    final item = FeedItem.fromJson({'id': 'a', 'title': null, 'author': 'x', 'duration': 12, 'cover': null, 'stream': '/api/files/a/stream'});
    expect((item.id, item.title, item.author, item.stream), ('a', '', 'x', '/api/files/a/stream'));
  });

  test('FeedItem reads favorite and resume position, defaults when absent', () {
    final saved = FeedItem.fromJson({'id': 'a', 'stream': '/s', 'favorite': true, 'position': 12.5});
    expect((saved.favorite, saved.position), (true, 12.5));
    final plain = FeedItem.fromJson({'id': 'b', 'stream': '/s'});
    expect((plain.favorite, plain.position), (false, 0));
  });

  test('Blogger and Me parse server payloads', () {
    final blogger = Blogger.fromJson({'author': 'alice', 'count': 3, 'avatar': '/api/covers/x', 'signature': null, 'platform': 'douyin', 'followers': 12000});
    expect((blogger.author, blogger.count, blogger.avatar, blogger.signature, blogger.followers), ('alice', 3, '/api/covers/x', '', 12000));
    final bare = Blogger.fromJson({'author': 'bob', 'count': 1});
    expect((bare.avatar, bare.followers, bare.platform), (null, null, ''));
    final me = Me.fromJson({'username': 'admin', 'avatar': null, 'background': 7, 'favorites': 2, 'history': 5, 'videos': 40});
    expect((me.username, me.avatar, me.background, me.favorites, me.history, me.videos), ('admin', null, 7, 2, 5, 40));
  });

  test('number and duration formatting', () {
    expect(formatCount(950), '950');
    expect(formatCount(12345), '1.2 万');
    expect(formatCount(1234567), '123 万');
    expect(formatDuration(null), '');
    expect(formatDuration(0), '');
    expect(formatDuration(75.4), '01:15');
    expect(platformLabel('douyin'), '抖音');
    expect(platformLabel('unknown'), 'unknown');
  });

  testWidgets('login page shows its fields', (tester) async {
    await tester.pumpWidget(MaterialApp(home: LoginPage(onLogin: (_) {}, initialServer: 'http://nas:8765')));
    expect(find.text('服务器地址'), findsOneWidget);
    expect(find.text('登录'), findsOneWidget);
    expect(find.text('http://nas:8765'), findsOneWidget);
  });
}
