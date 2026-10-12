import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harbor_mobile/add_subscription_page.dart';
import 'package:harbor_mobile/api.dart';
import 'package:harbor_mobile/console_api.dart';
import 'package:harbor_mobile/console_models.dart';
import 'package:harbor_mobile/subscription_settings.dart';

Map<String, dynamic> subJson({Map<String, dynamic>? runtime, Map<String, dynamic>? extra}) => {
      'id': 's1', 'platform': 'douyin', 'subscription_type': 'like', 'nickname': '我 的点赞', 'user_id': 'SEC', 'auto_download': false,
      'generate_nfo': true, 'quality': 'best', 'update_interval': 28800, 'status': 'active',
      'runtime': {'stored_videos': 12, 'check_available': true, 'manual_sync_available': true, ...?runtime},
      ...?extra,
    };

void main() {
  group('subscriptions', () {
    test('parse a decorated subscription and its labels', () {
      final sub = Subscription.fromJson(subJson());
      expect((sub.nickname, sub.label, sub.autoDownload, sub.runtime.storedVideos), ('我 的点赞', '抖音·我的点赞', false, 12));
      expect(sub.stateText, '自动检查');
      expect(subscriptionLabel('douyin', 'mix'), '抖音·合集');
      expect(subscriptionLabel('douyin', 'user'), '抖音');
      expect(subscriptionLabel('bilibili', 'user'), '哔哩哔哩');
    });

    test('state text puts what needs attention first', () {
      Subscription with_(Map<String, dynamic> runtime, {Map<String, dynamic>? extra}) => Subscription.fromJson(subJson(runtime: runtime, extra: extra));
      expect(with_({'is_syncing': true, 'auth_expired': true}).stateText, '同步中');
      expect(with_({'auth_expired': true}).stateText, '需要重新登录');
      expect(with_({'last_error': '风控'}).stateText, '检查失败');
      expect(with_({'last_error': ''}).stateText, '自动检查');
      expect(with_({}, extra: {'update_interval': 0, 'status': 'paused'}).stateText, '已暂停');
      expect(with_({'check_available': false}).stateText, '仅手动同步');
      expect(with_({'auth_expired': true}).needsAttention, isTrue);
      expect(with_({}).needsAttention, isFalse);
    });

    test('a blank nickname falls back to the platform id, an absent type means user', () {
      final sub = Subscription.fromJson({...subJson(), 'nickname': '', 'subscription_type': null});
      expect((sub.nickname, sub.type), ('SEC', 'user'));
    });

    test('sync progress text, fraction and queue', () {
      final running = SyncProgress.fromJson({'state': 'running', 'mode': 'sync', 'pages': 3, 'fetched': 50, 'total': 200, 'queue_position': 0})!;
      expect((running.fraction, running.text), (0.25, '全量同步中：已读取 50 个作品，3 页'));
      final queued = SyncProgress.fromJson({'state': 'queued', 'mode': 'check', 'pages': 0, 'fetched': 0, 'total': null, 'queue_position': 2})!;
      expect((queued.queued, queued.fraction), (true, null));
      expect(queued.text, contains('排队'));
      expect(SyncProgress.fromJson(null), isNull);
      expect(SyncProgress.fromJson({'state': 'running', 'mode': 'sync', 'fetched': 500, 'total': 100})!.fraction, 1.0);
    });

    test('work stats count what a download-all would queue', () {
      final stats = WorkStats.fromJson({'total': 10, 'downloaded_count': 4, 'downloading_count': 1, 'not_downloaded_count': 3, 'failed_count': 1, 'cancelled_count': 0, 'orphaned_count': 1});
      expect((stats.total, stats.pending), (10, 5));
    });

    test('works: status, playability and the real author', () {
      final work = SubWork.fromJson({
        'id': 'w', 'video_id': '1', 'title': 't', 'status': 'downloaded', 'asset_id': 'a', 'media_kind': 'video', 'cover_local': '/api/covers/x',
        'cover_url': 'https://remote/x.jpg', 'task_progress': 100, 'extra_data': {'author': {'name': '原作者'}},
      });
      expect((work.playable, work.pending, work.author, work.cover), (true, false, '原作者', '/api/covers/x'));
      final gallery = SubWork.fromJson({'id': 'g', 'status': 'downloaded', 'asset_id': 'a', 'media_kind': 'image'});
      expect(gallery.playable, isFalse);
      final failed = SubWork.fromJson({'id': 'f', 'status': 'failed', 'cover_url': 'https://remote/x.jpg'});
      expect((failed.pending, failed.cover), (true, 'https://remote/x.jpg'));
      expect(workStatusLabel('downloading', taskStatus: 'PENDING'), '排队中');
      expect(workStatusLabel('orphaned'), '文件缺失');
    });

    test('batch and check results read as one sentence', () {
      expect(BatchResult.fromJson({'requested': 0}).summary, '没有需要下载的作品');
      final batch = BatchResult.fromJson({'requested': 5, 'queued': 3, 'linked': 1, 'skipped': 0, 'errors': [{'video_id': 'x', 'message': '失败'}]});
      expect(batch.summary, '已加入下载 3 个，1 个已在其他订阅下载过，直接关联，1 个失败');
      expect(CheckResult.fromJson({'new_videos_count': 0}).summary, '没有新作品');
      expect(CheckResult.fromJson({'new_videos_count': 4, 'queued_count': 2, 'may_have_more': true}).summary, contains('建议全量同步'));
    });

    test('only changed settings are sent', () {
      final sub = Subscription.fromJson(subJson());
      expect(settingsChanges(sub, nickname: '我 的点赞 ', interval: 28800, auto: false, nfo: true, quality: 'best'), isEmpty);
      expect(settingsChanges(sub, nickname: '收藏夹', interval: 3600, auto: true, nfo: false, quality: '720'),
          {'nickname': '收藏夹', 'update_interval': 3600, 'auto_download': true, 'generate_nfo': false, 'quality': '720'});
      expect(settingsChanges(sub, nickname: '   ', interval: 28800, auto: false, nfo: true, quality: 'best'), isEmpty);
    });
  });

  group('downloads and system', () {
    test('task rows: status text, what can be done', () {
      final running = TaskRow.fromJson({'id': 't', 'title': '', 'url': 'https://x/y', 'status': 'DOWNLOADING', 'progress': 42.5, 'speed': '1MiB/s'});
      expect((running.title, running.active, running.canRetry, running.statusText), ('https://x/y', true, false, '下载中'));
      final failed = TaskRow.fromJson({'id': 't', 'title': 'a', 'url': 'u', 'status': 'ERROR', 'error': 'boom'});
      expect((failed.active, failed.canRetry, failed.error), (false, true, 'boom'));
      expect(TaskRow.fromJson({'id': 't', 'status': 'ERROR', 'error': ''}).error, isNull);
    });

    test('parsed media offers its formats', () {
      final info = MediaInfo.fromJson({'url': 'u', 'title': 'T', 'formats': [{'id': '137+140', 'label': '1080p', 'kind': 'video'}, {'id': '140', 'label': '仅音频', 'kind': 'audio'}]});
      expect((info.formats.length, info.formats.first.id, info.formats.last.kind, info.thumbnail), (2, '137+140', 'audio', null));
    });

    test('overview and settings', () {
      final overview = Overview.fromJson({'counts': {'DOWNLOADING': 2, 'PROCESSING': 1, 'PENDING': 4, 'ERROR': 3}, 'disk': {'total': 1000, 'free': 250}, 'downloaded_bytes': 5});
      expect((overview.running, overview.queued, overview.failed, overview.diskUsedFraction), (3, 4, 3, 0.75));
      expect(Overview.fromJson({}).diskUsedFraction, 0);
      final settings = ServerSettings.fromJson({'concurrency': 2, 'sync_concurrency': 1, 'version': '0.1.0', 'ffmpeg_available': true});
      expect((settings.concurrency, settings.ffmpeg), (2, true));
    });

    test('cookie status shows which logins are saved', () {
      final status = CookieStatus.fromJson({'cookies': {'douyin': {'exists': true, 'updated_at': '2026-10-01T00:00:00+00:00'}, 'youtube': {'exists': false}}});
      expect((status.saved['douyin'], status.saved['youtube']), ('2026-10-01T00:00:00+00:00', null));
    });

    test('logs name their source', () {
      expect(LogEntry.fromJson({'source': 'subscription', 'title': 't', 'message': 'm', 'time': ''}).sourceText, '订阅');
    });
  });

  group('formatting', () {
    test('bytes', () {
      expect(formatBytes(0), '0 B');
      expect(formatBytes(1536), '1.5 KB');
      expect(formatBytes(5 * 1024 * 1024 * 1024), '5.0 GB');
      expect(formatBytes(250 * 1024 * 1024), '250 MB');
    });

    test('intervals', () {
      expect(intervalLabel(28800), '每 8 小时');
      expect(intervalLabel(0), '暂停自动检查');
      expect(intervalLabel(5400), '每 90 分钟');
      expect(intervalLabel(10800), '每 3 小时');
    });

    test('relative time, past and future', () {
      final now = DateTime.utc(2026, 10, 12, 12);
      expect(relativeTime(null), '尚未检查');
      expect(relativeTime('pending'), '即将进行');
      expect(relativeTime('garbage'), '—');
      expect(relativeTime('2026-10-12T11:56:00+00:00', now: now), '4 分钟前');
      expect(relativeTime('2026-10-12T09:00:00+00:00', now: now), '3 小时前');
      expect(relativeTime('2026-10-10T12:00:00+00:00', now: now), '2 天前');
      expect(relativeTime('2026-10-12T12:00:10+00:00', now: now), '刚刚');
      expect(relativeTime('2026-10-12T14:00:00+00:00', now: now, future: true), '2 小时后');
      expect(relativeTime('2026-10-12T12:00:10+00:00', now: now, future: true), '即将');
    });
  });

  group('errors', () {
    test('the server detail wins, a weak token is explained, 5xx never leaks nothing', () {
      expect(explainError(409, {'detail': '该订阅已存在'}, 'x'), '该订阅已存在');
      expect(explainError(422, {'detail': '请输入链接'}, 'x'), '请输入链接');
      expect(explainError(422, null, 'x'), '输入内容无效');
      expect(explainError(403, {'detail': '此 Token 的权限范围（read）不足，该操作需要 download'}, 'x'), contains('权限不足'));
      expect(explainError(403, null, 'x'), contains('重新登录'));
      expect(explainError(502, {'detail': '抖音请求被拒绝'}, 'x'), '抖音请求被拒绝');
      expect(explainError(500, null, 'x'), '服务器出错了');
      expect(explainError(null, null, '加载失败'), '加载失败');
      expect(explainError(404, 'not a map', '加载失败'), '加载失败');
    });
  });

  group('add subscription page', () {
    Api api() => Api(Session('http://server', 'token'));

    testWidgets('likes need no link, a link kind does', (tester) async {
      await tester.pumpWidget(MaterialApp(home: AddSubscriptionPage(api: api(), onLogout: () {})));
      expect(find.text('添加订阅'), findsOneWidget);
      expect(find.byType(TextField), findsNWidgets(2));       // link + nickname
      await tester.tap(find.text('我的点赞'));
      await tester.pump();
      expect(find.byType(TextField), findsOneWidget);          // nickname only
      expect(find.textContaining('无需链接'), findsOneWidget);
      await tester.tap(find.text('抖音合集'));
      await tester.pump();
      expect(find.text('从我收藏的合集里选'), findsOneWidget);
    });

    testWidgets('submitting without a link says so instead of calling the server', (tester) async {
      await tester.pumpWidget(MaterialApp(home: AddSubscriptionPage(api: api(), onLogout: () {})));
      await tester.scrollUntilVisible(find.text('解析并添加'), 200, scrollable: find.byType(Scrollable).first);
      await tester.tap(find.text('解析并添加'));
      await tester.pump();
      expect(find.text('请先填写链接'), findsOneWidget);
    });
  });
}
