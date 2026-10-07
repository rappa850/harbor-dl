import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class FeedItem {
  FeedItem(this.id, this.title, this.author, this.duration, this.cover, this.stream,
      {this.favorite = false, this.position = 0});

  final String id, title, author, stream;
  final num? duration;
  final String? cover;
  bool favorite;
  final num position;

  factory FeedItem.fromJson(Map<String, dynamic> j) => FeedItem(
      j['id'] as String, (j['title'] ?? '') as String, (j['author'] ?? '') as String,
      j['duration'] as num?, j['cover'] as String?, j['stream'] as String,
      favorite: (j['favorite'] ?? false) as bool, position: (j['position'] ?? 0) as num);
}

class FeedPageData {
  FeedPageData(this.items, this.next, this.total);
  final List<FeedItem> items;
  final String? next;
  final int total;
}

/// Server address + bearer token, kept in the platform keystore.
class Session {
  Session(this.server, this.token);
  final String server, token;

  static const _store = FlutterSecureStorage();

  static Future<Session?> restore() async {
    final server = await _store.read(key: 'server'), token = await _store.read(key: 'token');
    return server == null || token == null ? null : Session(server, token);
  }

  static Future<void> clear() async {
    await _store.delete(key: 'server');
    await _store.delete(key: 'token');
  }

  Future<void> save() async {
    await _store.write(key: 'server', value: server);
    await _store.write(key: 'token', value: token);
  }

  Map<String, String> get headers => {'Authorization': 'Bearer $token'};
  String url(String path) => '$server$path';
}

String normalizeServer(String input) {
  var value = input.trim();
  if (!value.contains('://')) value = 'http://$value';
  while (value.endsWith('/')) {
    value = value.substring(0, value.length - 1);
  }
  return value;
}

class Unauthorized implements Exception {}

class Api {
  Api(this.session)
      : _dio = Dio(BaseOptions(
            baseUrl: session.server,
            headers: session.headers,
            connectTimeout: const Duration(seconds: 10),
            receiveTimeout: const Duration(seconds: 20)));

  final Session session;
  final Dio _dio;

  /// Exchange a username/password for a long-lived token; throws a readable message on failure.
  static Future<Session> login(String server, String username, String password, String device) async {
    final base = normalizeServer(server);
    try {
      final response = await Dio(BaseOptions(baseUrl: base, connectTimeout: const Duration(seconds: 10)))
          .post('/api/auth/app-login', data: {'username': username, 'password': password, 'device': device});
      return Session(base, response.data['token'] as String);
    } on DioException catch (e) {
      if (e.response?.statusCode == 401) throw '用户名或密码错误';
      if (e.response?.statusCode == 422) throw '用户名或密码格式不正确';
      throw '无法连接到 $base';
    }
  }

  Future<FeedPageData> feed({String? cursor, String mode = 'latest', String seed = '', String author = '', int limit = 20}) async {
    try {
      final response = await _dio.get('/api/feed', queryParameters: {
        'limit': limit, 'mode': mode, 'seed': seed, 'cursor': ?cursor, if (author.isNotEmpty) 'author': author});
      final data = response.data as Map<String, dynamic>;
      return FeedPageData(
          [for (final raw in data['items'] as List) FeedItem.fromJson(raw as Map<String, dynamic>)],
          data['next'] as String?,
          data['total'] as int);
    } on DioException catch (e) {
      if (e.response?.statusCode == 401) throw Unauthorized();
      throw '加载失败，请检查网络';
    }
  }

  /// Best effort: a failed call never interrupts playback; callers that need the outcome check the result.
  Future<bool> setFavorite(String id, bool on) async {
    try {
      on ? await _dio.put('/api/favorites/$id') : await _dio.delete('/api/favorites/$id');
      return true;
    } on DioException {
      return false;
    }
  }

  Future<void> watched(String id, num position) async {
    try {
      await _dio.post('/api/history', data: {'asset_id': id, 'position': position});
    } on DioException {
      // history is a convenience; losing one entry is fine
    }
  }
}
