import 'package:dio/dio.dart';

import 'api.dart';
import 'console_models.dart';

/// A readable message for a failed call: the server's own `detail` when it sent one, a hint for a token that is too
/// weak, else [fallback]. Pure so it can be tested without a network.
String explainError(int? status, Object? body, String fallback) {
  final detail = body is Map ? body['detail'] : null;
  final text = detail is String && detail.isNotEmpty ? detail : null;
  if (status == 403) return '权限不足：${text ?? '此设备的登录权限不够'}。请退出后重新登录。';
  if (status == 422 && text == null) return '输入内容无效';
  if (text != null && status != null && status >= 400 && status < 500) return text;
  if (status != null && status >= 500) return text ?? '服务器出错了';
  return fallback;
}

const _long = Duration(minutes: 10);

/// Console calls: subscriptions, downloads and system status. Everything the web page does with these, minus what needs a
/// desktop browser (logging in to a platform) or a browser session (passwords, token management).
extension ConsoleApi on Api {
  Future<T> guarded<T>(Future<T> Function() run, {String fallback = '操作失败，请检查网络'}) async {
    try {
      return await run();
    } on DioException catch (e) {
      final status = e.response?.statusCode;
      if (status == 401) throw Unauthorized();
      throw explainError(status, e.response?.data, e.type == DioExceptionType.receiveTimeout ? '服务器响应超时，操作可能仍在后台进行' : fallback);
    }
  }

  Map<String, dynamic> _map(Response<dynamic> r) => r.data as Map<String, dynamic>;

  // ---- subscriptions ----

  Future<List<Subscription>> subscriptions() => guarded(() async {
        final data = _map(await dio.get('/api/subscriptions'));
        return [for (final raw in data['items'] as List) Subscription.fromJson(raw as Map<String, dynamic>)];
      }, fallback: '加载失败，请检查网络');

  Future<Subscription> subscription(String id) =>
      guarded(() async => Subscription.fromJson(_map(await dio.get('/api/subscriptions/$id'))), fallback: '加载失败，请检查网络');

  Future<SyncProgress?> syncProgress(String id) =>
      guarded(() async => SyncProgress.fromJson(_map(await dio.get('/api/subscriptions/$id/sync-progress'))['progress']));

  Future<CheckResult> checkNow(String id) => guarded(() async =>
      CheckResult.fromJson(_map(await dio.post('/api/subscriptions/$id/check', options: Options(receiveTimeout: _long)))));

  /// Reads the whole history; resolves when the server is done (can take minutes), so callers poll [syncProgress] meanwhile.
  Future<int> fullSync(String id) => guarded(() async {
        final data = _map(await dio.post('/api/subscriptions/$id/sync', options: Options(receiveTimeout: _long)));
        return (data['new_videos_count'] as num?)?.toInt() ?? 0;
      });

  Future<WorkStats> workStats(String id) =>
      guarded(() async => WorkStats.fromJson(_map(await dio.get('/api/subscriptions/$id/videos/stats'))), fallback: '加载失败，请检查网络');

  Future<WorkPage> subscriptionWorks(String id, {int page = 1, int pageSize = 30, String status = 'all', String query = ''}) => guarded(() async {
        final data = _map(await dio.get('/api/subscriptions/$id/videos',
            queryParameters: {'page': page, 'page_size': pageSize, 'status': status, if (query.isNotEmpty) 'q': query}));
        return WorkPage([for (final raw in data['videos'] as List) SubWork.fromJson(raw as Map<String, dynamic>)], (data['total'] as num).toInt());
      }, fallback: '加载失败，请检查网络');

  /// [ids] = chosen works; null = everything still to do, optionally only the newest [limit].
  Future<BatchResult> downloadBatch(String id, {List<String>? ids, int? limit}) => guarded(() async =>
      BatchResult.fromJson(_map(await dio.post('/api/subscriptions/$id/videos/download', data: {'video_ids': ids, 'limit': ?limit}))));

  /// True when the work shared a download another subscription already made.
  Future<bool> downloadOne(String subscriptionId, String workId, {bool redownload = false}) => guarded(() async {
        final data = _map(await dio.post('/api/subscriptions/$subscriptionId/videos/$workId/download', data: {'redownload': redownload}));
        return data['linked'] == true;
      });

  Future<void> removeWork(String subscriptionId, String workId) =>
      guarded(() => dio.delete('/api/subscriptions/$subscriptionId/videos/$workId'));

  Future<void> cleanupMissing(String id) => guarded(() => dio.post('/api/subscriptions/$id/videos/orphan/cleanup', data: {'delete_residual': true}));

  Future<Subscription> editSubscription(String id, Map<String, dynamic> changes) =>
      guarded(() async => Subscription.fromJson(_map(await dio.patch('/api/subscriptions/$id', data: changes))));

  Future<void> deleteSubscription(String id) => guarded(() => dio.delete('/api/subscriptions/$id'));

  Future<Subscription> addSubscription(SubscriptionKind kind,
          {String link = '', String nickname = '', num interval = 28800, required bool autoDownload}) =>
      guarded(() async {
        final body = {
          'platform': kind.platform, 'source': kind.source, 'profile_url': kind.needsLink ? link.trim() : '', 'nickname': nickname.trim(),
          'update_interval': interval, 'auto_download': autoDownload,
          if (kind.id == 'youtube') 'youtube_tab_type': 'videos',
        };
        final response = await dio.post('/api/subscriptions', data: body, options: Options(receiveTimeout: const Duration(minutes: 2)));
        return Subscription.fromJson(_map(response));
      });

  Future<List<MixChoice>> collectedMixes() => guarded(() async {
        final data = _map(await dio.get('/api/douyin/collections', options: Options(receiveTimeout: const Duration(minutes: 2))));
        return [for (final raw in data['items'] as List) MixChoice.fromJson(raw as Map<String, dynamic>)];
      });

  // ---- downloads ----

  Future<TaskPage> tasks({String status = 'all', int offset = 0, int limit = 30}) => guarded(() async {
        final data = _map(await dio.get('/api/tasks', queryParameters: {'status': status, 'offset': offset, 'limit': limit}));
        return TaskPage([for (final raw in data['items'] as List) TaskRow.fromJson(raw as Map<String, dynamic>)], (data['total'] as num).toInt());
      }, fallback: '加载失败，请检查网络');

  Future<void> cancelTask(String id) => guarded(() => dio.post('/api/tasks/$id/cancel'));
  Future<void> retryTask(String id) => guarded(() => dio.post('/api/tasks/$id/retry'));
  Future<void> deleteTask(String id, {bool deleteFile = false}) =>
      guarded(() => dio.delete('/api/tasks/$id', queryParameters: {'delete_file': deleteFile}));

  Future<MediaInfo> parseLink(String text) => guarded(() async =>
      MediaInfo.fromJson(_map(await dio.post('/api/media/parse', data: {'text': text}, options: Options(receiveTimeout: const Duration(minutes: 2))))));

  Future<void> createTask(MediaInfo info, FormatChoice format) => guarded(() => dio.post('/api/tasks', data: {
        'url': info.url, 'title': info.title, 'author': info.author, 'format_id': format.id,
        if (info.thumbnail != null) 'cover_url': info.thumbnail,
      }));

  // ---- system ----

  Future<Overview> overview() =>
      guarded(() async => Overview.fromJson(_map(await dio.get('/api/dashboard'))), fallback: '加载失败，请检查网络');

  Future<ServerSettings> serverSettings() =>
      guarded(() async => ServerSettings.fromJson(_map(await dio.get('/api/settings'))), fallback: '加载失败，请检查网络');

  Future<void> saveConcurrency({required int downloads, required int syncs}) =>
      guarded(() => dio.put('/api/settings', data: {'concurrency': downloads, 'sync_concurrency': syncs}));

  Future<CookieStatus> cookieStatus() =>
      guarded(() async => CookieStatus.fromJson(_map(await dio.get('/api/network'))), fallback: '加载失败，请检查网络');

  Future<List<LogEntry>> failureLogs({String source = '', int limit = 50}) => guarded(() async {
        final data = _map(await dio.get('/api/logs', queryParameters: {'limit': limit, if (source.isNotEmpty) 'source': source}));
        return [for (final raw in data['items'] as List) LogEntry.fromJson(raw as Map<String, dynamic>)];
      }, fallback: '加载失败，请检查网络');
}
