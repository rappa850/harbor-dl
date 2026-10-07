import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harbor_mobile/api.dart';
import 'package:harbor_mobile/login_page.dart';

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

  testWidgets('login page shows its fields', (tester) async {
    await tester.pumpWidget(MaterialApp(home: LoginPage(onLogin: (_) {}, initialServer: 'http://nas:8765')));
    expect(find.text('服务器地址'), findsOneWidget);
    expect(find.text('登录'), findsOneWidget);
    expect(find.text('http://nas:8765'), findsOneWidget);
  });
}
