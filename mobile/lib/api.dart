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

class Blogger {
  Blogger(this.author, this.count, this.avatar, this.signature, this.platform, this.followers);

  final String author, signature, platform;
  final int count;
  final String? avatar;
  final int? followers;

  factory Blogger.fromJson(Map<String, dynamic> j) => Blogger(
      j['author'] as String, j['count'] as int, j['avatar'] as String?, (j['signature'] ?? '') as String,
      (j['platform'] ?? '') as String, j['followers'] as int?);
}

/// What the profile tab shows. [avatar] and [background] are cache-busting versions, null when not set.
class Me {
  Me(this.username, this.avatar, this.background, this.favorites, this.history, this.videos);

  final String username;
  final int? avatar, background;
  final int favorites, history, videos;

  factory Me.fromJson(Map<String, dynamic> j) => Me(j['username'] as String, j['avatar'] as int?,
      j['background'] as int?, j['favorites'] as int, j['history'] as int, j['videos'] as int);
}

/// Where a tapped grid cell should start the full-screen feed: the loaded items, the position and how to continue.
class FeedSeed {
  FeedSeed(this.items, this.next, this.index);

  final List<FeedItem> items;
  final String? next;
  final int index;
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

  Future<T> _read<T>(Future<T> Function() call) async {
    try {
      return await call();
    } on DioException catch (e) {
      if (e.response?.statusCode == 401) throw Unauthorized();
      throw '加载失败，请检查网络';
    }
  }

  Future<List<Blogger>> bloggers({String query = '', String sort = 'recent'}) => _read(() async {
        final response = await _dio.get('/api/bloggers', queryParameters: {'q': query, 'sort': sort});
        return [for (final raw in response.data['items'] as List) Blogger.fromJson(raw as Map<String, dynamic>)];
      });

  Future<Blogger> blogger(String author) => _read(() async {
        final response = await _dio.get('/api/blogger', queryParameters: {'author': author});
        return Blogger.fromJson(response.data as Map<String, dynamic>);
      });

  Future<Me> me() => _read(() async => Me.fromJson((await _dio.get('/api/app/me')).data as Map<String, dynamic>));

  /// [kind] is 'avatar' or 'background'. Throws a readable message when the server refuses the picture.
  Future<void> putPicture(String kind, List<int> bytes) async {
    try {
      await _dio.put('/api/auth/$kind',
          data: Stream.value(bytes),
          options: Options(headers: {Headers.contentLengthHeader: bytes.length, Headers.contentTypeHeader: 'application/octet-stream'}));
    } on DioException catch (e) {
      if (e.response?.statusCode == 413) throw '图片太大了';
      if (e.response?.statusCode == 415) throw '只支持 PNG、JPEG 或 WebP 图片';
      throw '上传失败，请检查网络';
    }
  }

  Future<void> deletePicture(String kind) => _read(() => _dio.delete('/api/auth/$kind'));

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
