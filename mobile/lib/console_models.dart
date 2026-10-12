/// Models and labels for the console tabs (subscriptions, downloads, system). Parsing only; no I/O.
library;

num? _num(Object? v) => v is num ? v : null;
int _int(Object? v) => v is num ? v.toInt() : 0;
String _str(Object? v) => v is String ? v : '';
Map<String, dynamic> _obj(Object? v) => v is Map ? v.cast<String, dynamic>() : const <String, dynamic>{};

/// What the "add subscription" form can create. [source] is the `source` field of `POST /api/subscriptions`.
class SubscriptionKind {
  const SubscriptionKind(this.id, this.label, this.platform, this.source, this.hint, {this.needsLink = true, this.needsLogin = false, this.autoDownloadDefault = false});

  final String id, label, platform, source, hint;
  final bool needsLink, needsLogin, autoDownloadDefault;
}

const kSubscriptionKinds = [
  SubscriptionKind('douyin', '抖音博主', 'douyin', 'user', '博主主页链接或分享短链接', needsLogin: true),
  SubscriptionKind('douyin_like', '我的点赞', 'douyin', 'like', '读取登录账号点赞过的作品，无需链接', needsLink: false, needsLogin: true),
  SubscriptionKind('douyin_favorite', '我的收藏', 'douyin', 'favorite', '读取登录账号收藏的作品，无需链接', needsLink: false, needsLogin: true),
  SubscriptionKind('douyin_mix', '抖音合集', 'douyin', 'mix', '合集链接、分享短链接或合集 ID', needsLogin: true),
  SubscriptionKind('youtube', 'YouTube 频道', 'youtube', 'user', '频道主页链接'),
  SubscriptionKind('youtube_playlist', 'YouTube 歌单', 'youtube_playlist', 'user', '歌单链接或 PL 开头的标识'),
  SubscriptionKind('bilibili', 'B 站作者', 'bilibili', 'user', '作者空间链接'),
];

const _platformNames = {
  'douyin': '抖音', 'youtube': 'YouTube', 'youtube_playlist': 'YouTube 歌单', 'bilibili': '哔哩哔哩',
  'bilibili_collection': 'B 站合集', 'tiktok': 'TikTok', 'instagram': 'Instagram', 'x': 'X',
};

/// 'Douyin · my likes' style label shown on list tiles.
String subscriptionLabel(String platform, String type) {
  final name = _platformNames[platform] ?? platform;
  if (platform == 'douyin') {
    return switch (type) { 'like' => '$name·我的点赞', 'favorite' => '$name·我的收藏', 'mix' => '$name·合集', _ => name };
  }
  return name;
}

class SubRuntime {
  SubRuntime({
    this.storedVideos = 0, this.isSyncing = false, this.lastCheckedAt, this.lastError, this.authExpired = false,
    this.moreAvailable = false, this.checkAvailable = false, this.manualSyncAvailable = false, this.unavailableReason,
    this.lastNew = 0, this.lastQueued = 0, this.lastMode, this.nextCheckAt,
  });

  final int storedVideos, lastNew, lastQueued;
  final bool isSyncing, authExpired, moreAvailable, checkAvailable, manualSyncAvailable;
  final String? lastCheckedAt, lastError, unavailableReason, lastMode, nextCheckAt;

  factory SubRuntime.fromJson(Map<String, dynamic> j) => SubRuntime(
      storedVideos: _int(j['stored_videos']), isSyncing: j['is_syncing'] == true, lastCheckedAt: j['last_checked_at'] as String?,
      lastError: (j['last_error'] as String?)?.isEmpty == true ? null : j['last_error'] as String?, authExpired: j['auth_expired'] == true,
      moreAvailable: j['more_available'] == true, checkAvailable: j['check_available'] == true,
      manualSyncAvailable: j['manual_sync_available'] == true, unavailableReason: j['unavailable_reason'] as String?,
      lastNew: _int(j['last_new_count']), lastQueued: _int(j['last_queued_count']), lastMode: j['last_mode'] as String?,
      nextCheckAt: j['next_check_at'] as String?);
}

class Subscription {
  Subscription({
    required this.id, required this.platform, required this.type, required this.nickname, required this.userId,
    required this.autoDownload, required this.generateNfo, required this.quality, required this.updateInterval,
    required this.status, required this.runtime, this.avatarUrl,
  });

  final String id, platform, type, nickname, userId, quality, status;
  final bool autoDownload, generateNfo;
  final double updateInterval;
  final String? avatarUrl;
  final SubRuntime runtime;

  String get label => subscriptionLabel(platform, type);
  bool get paused => status == 'paused' || updateInterval <= 0;

  /// The one-line state shown on the list: what needs the user's attention first.
  String get stateText {
    if (runtime.isSyncing) return '同步中';
    if (runtime.authExpired) return '需要重新登录';
    if (runtime.lastError != null) return '检查失败';
    if (paused) return '已暂停';
    if (!runtime.checkAvailable) return '仅手动同步';
    return '自动检查';
  }

  bool get needsAttention => runtime.authExpired || runtime.lastError != null;

  factory Subscription.fromJson(Map<String, dynamic> j) => Subscription(
      id: j['id'] as String, platform: _str(j['platform']), type: _str(j['subscription_type']).isEmpty ? 'user' : _str(j['subscription_type']),
      nickname: _str(j['nickname']).isEmpty ? _str(j['user_id']) : _str(j['nickname']), userId: _str(j['user_id']),
      autoDownload: j['auto_download'] == true, generateNfo: j['generate_nfo'] != false, quality: _str(j['quality']).isEmpty ? 'best' : _str(j['quality']),
      updateInterval: (_num(j['update_interval']) ?? 0).toDouble(), status: _str(j['status']),
      avatarUrl: j['avatar_url'] as String?, runtime: SubRuntime.fromJson(_obj(j['runtime'])));
}

/// Live state of a running or queued sync / check (from `/sync-progress`), null when idle.
class SyncProgress {
  SyncProgress(this.state, this.mode, this.pages, this.fetched, this.total, this.queuePosition);

  final String state, mode;
  final int pages, fetched, queuePosition;
  final int? total;

  bool get queued => state == 'queued';

  /// 0..1 when the platform told us how many works there are, else null (indeterminate).
  double? get fraction => total == null || total! <= 0 ? null : (fetched / total!).clamp(0.0, 1.0);

  String get text {
    final what = mode == 'sync' ? '全量同步' : '检查更新';
    if (queued) return '$what排队中（前面还有 $queuePosition 个）';
    return '$what中：已读取 $fetched 个作品，$pages 页';
  }

  static SyncProgress? fromJson(Object? raw) {
    if (raw is! Map<String, dynamic>) return null;
    return SyncProgress(_str(raw['state']), _str(raw['mode']), _int(raw['pages']), _int(raw['fetched']), _num(raw['total'])?.toInt(), _int(raw['queue_position']));
  }
}

class WorkStats {
  WorkStats({this.total = 0, this.downloaded = 0, this.downloading = 0, this.notDownloaded = 0, this.failed = 0, this.cancelled = 0, this.orphaned = 0});

  final int total, downloaded, downloading, notDownloaded, failed, cancelled, orphaned;

  /// Works the "download everything" action would queue.
  int get pending => notDownloaded + failed + cancelled + orphaned;

  factory WorkStats.fromJson(Map<String, dynamic> j) => WorkStats(
      total: _int(j['total']), downloaded: _int(j['downloaded_count']), downloading: _int(j['downloading_count']),
      notDownloaded: _int(j['not_downloaded_count']), failed: _int(j['failed_count']), cancelled: _int(j['cancelled_count']),
      orphaned: _int(j['orphaned_count']));
}

const kWorkStatuses = [
  ('all', '全部'), ('downloaded', '已下载'), ('downloading', '下载中'), ('not_downloaded', '未下载'), ('failed', '失败'), ('orphaned', '文件缺失'),
];

String workStatusLabel(String status, {String? taskStatus}) {
  if (taskStatus == 'PENDING') return '排队中';
  if (taskStatus == 'PROCESSING') return '处理中';
  return switch (status) {
    'downloaded' => '已下载', 'downloading' => '下载中', 'not_downloaded' => '未下载', 'failed' => '下载失败',
    'cancelled' => '已取消', 'orphaned' => '文件缺失', _ => status,
  };
}

class SubWork {
  SubWork({
    required this.id, required this.videoId, required this.title, required this.status, this.taskStatus, this.cover, this.duration,
    this.publishTime, this.assetId, this.mediaKind, this.progress, this.error, this.author,
  });

  final String id, videoId, title, status;
  final String? taskStatus, cover, publishTime, assetId, mediaKind, error, author;
  final num? duration, progress;

  bool get playable => status == 'downloaded' && assetId != null && (mediaKind == 'video');
  bool get pending => const ['not_downloaded', 'failed', 'cancelled', 'orphaned'].contains(status);

  factory SubWork.fromJson(Map<String, dynamic> j) {
    final extra = j['extra_data'];
    final author = extra is Map ? (extra['author'] is Map ? (extra['author'] as Map)['name'] as String? : null) : null;
    return SubWork(
        id: j['id'] as String, videoId: _str(j['video_id']), title: _str(j['title']), status: _str(j['status']),
        taskStatus: j['task_status'] as String?, cover: (j['cover_local'] ?? j['cover_url']) as String?, duration: _num(j['duration']),
        publishTime: j['publish_time'] as String?, assetId: j['asset_id'] as String?, mediaKind: j['media_kind'] as String?,
        progress: _num(j['task_progress']), error: j['error_message'] as String?, author: author);
  }
}

class WorkPage {
  WorkPage(this.items, this.total);
  final List<SubWork> items;
  final int total;
}

class BatchResult {
  BatchResult(this.requested, this.queued, this.linked, this.skipped, this.errors);

  final int requested, queued, linked, skipped;
  final List<String> errors;

  factory BatchResult.fromJson(Map<String, dynamic> j) => BatchResult(_int(j['requested']), _int(j['queued']), _int(j['linked']), _int(j['skipped']),
      [for (final e in (j['errors'] as List? ?? const [])) if (e is Map) _str(e['message'])]);

  String get summary {
    if (requested == 0) return '没有需要下载的作品';
    final parts = <String>['已加入下载 $queued 个'];
    if (linked > 0) parts.add('$linked 个已在其他订阅下载过，直接关联');
    if (skipped > 0) parts.add('跳过 $skipped 个');
    if (errors.isNotEmpty) parts.add('${errors.length} 个失败');
    return parts.join('，');
  }
}

class CheckResult {
  CheckResult(this.newCount, this.queued, this.linked, this.mayHaveMore);

  final int newCount, queued, linked;
  final bool mayHaveMore;

  factory CheckResult.fromJson(Map<String, dynamic> j) => CheckResult(
      _int(j['new_videos_count']), _int(j['queued_count']), _int(j['linked_count']), j['may_have_more'] == true);

  String get summary {
    if (newCount == 0) return '没有新作品';
    return '发现 $newCount 个新作品${queued > 0 ? '，已加入下载 $queued 个' : ''}${mayHaveMore ? '；可能还有更多，建议全量同步' : ''}';
  }
}

class MixChoice {
  MixChoice(this.id, this.title, this.author, this.count);

  final String id, title;
  final String? author;
  final int? count;

  factory MixChoice.fromJson(Map<String, dynamic> j) =>
      MixChoice(_str(j['mix_id']), _str(j['title']), j['author'] as String?, _num(j['count'])?.toInt());
}

// ---- downloads ----------------------------------------------------------------------------------------------------

const kTaskFilters = [('all', '全部'), ('active', '进行中'), ('completed', '已完成'), ('error', '失败')];

class TaskRow {
  TaskRow({required this.id, required this.title, required this.status, required this.progress, required this.speed, required this.url, this.error, this.author, this.subscriptionId});

  final String id, title, status, speed, url;
  final num progress;
  final String? error, author, subscriptionId;

  bool get active => const ['PENDING', 'DOWNLOADING', 'PROCESSING'].contains(status);
  bool get canRetry => status == 'ERROR' || status == 'CANCELLED';

  String get statusText => switch (status) {
        'PENDING' => '排队中', 'DOWNLOADING' => '下载中', 'PROCESSING' => '处理中', 'COMPLETED' => '已完成',
        'ERROR' => '失败', 'CANCELLED' => '已取消', _ => status,
      };

  factory TaskRow.fromJson(Map<String, dynamic> j) => TaskRow(
      id: j['id'] as String, title: _str(j['title']).isEmpty ? _str(j['url']) : _str(j['title']), status: _str(j['status']),
      progress: _num(j['progress']) ?? 0, speed: _str(j['speed']), url: _str(j['url']),
      error: (j['error'] as String?)?.isEmpty == true ? null : j['error'] as String?, author: j['author'] as String?,
      subscriptionId: j['subscription_id'] as String?);
}

class TaskPage {
  TaskPage(this.items, this.total);
  final List<TaskRow> items;
  final int total;
}

class FormatChoice {
  FormatChoice(this.id, this.label, this.kind);

  final String id, label, kind;

  factory FormatChoice.fromJson(Map<String, dynamic> j) => FormatChoice(_str(j['id']), _str(j['label']), _str(j['kind']));
}

class MediaInfo {
  MediaInfo(this.url, this.title, this.author, this.thumbnail, this.duration, this.formats);

  final String url, title, author;
  final String? thumbnail;
  final num? duration;
  final List<FormatChoice> formats;

  factory MediaInfo.fromJson(Map<String, dynamic> j) => MediaInfo(
      _str(j['url']), _str(j['title']), _str(j['author']), j['thumbnail'] as String?, _num(j['duration']),
      [for (final f in (j['formats'] as List? ?? const [])) FormatChoice.fromJson(f as Map<String, dynamic>)]);
}

// ---- system -------------------------------------------------------------------------------------------------------

class Overview {
  Overview({required this.counts, required this.diskFree, required this.diskTotal, required this.downloadedBytes});

  final Map<String, int> counts;
  final int diskFree, diskTotal, downloadedBytes;

  int get running => (counts['DOWNLOADING'] ?? 0) + (counts['PROCESSING'] ?? 0);
  int get queued => counts['PENDING'] ?? 0;
  int get failed => counts['ERROR'] ?? 0;
  double get diskUsedFraction => diskTotal <= 0 ? 0 : ((diskTotal - diskFree) / diskTotal).clamp(0.0, 1.0);

  factory Overview.fromJson(Map<String, dynamic> j) {
    final disk = _obj(j['disk']);
    return Overview(
        counts: {for (final e in _obj(j['counts']).entries) e.key: _int(e.value)},
        diskFree: _int(disk['free']), diskTotal: _int(disk['total']), downloadedBytes: _int(j['downloaded_bytes']));
  }
}

class ServerSettings {
  ServerSettings(this.concurrency, this.syncConcurrency, this.version, this.ffmpeg);

  final int concurrency, syncConcurrency;
  final String version;
  final bool ffmpeg;

  factory ServerSettings.fromJson(Map<String, dynamic> j) =>
      ServerSettings(_int(j['concurrency']), _int(j['sync_concurrency']), _str(j['version']), j['ffmpeg_available'] == true);
}

/// Saved platform logins: platform id -> when it was saved (null = none saved).
class CookieStatus {
  CookieStatus(this.saved);

  final Map<String, String?> saved;

  factory CookieStatus.fromJson(Map<String, dynamic> j) {
    final cookies = _obj(j['cookies']);
    return CookieStatus({
      for (final e in cookies.entries) e.key: (e.value is Map && (e.value as Map)['exists'] == true) ? _str((e.value as Map)['updated_at']) : null,
    });
  }
}

class LogEntry {
  LogEntry(this.source, this.title, this.message, this.time);

  final String source, title, message, time;

  String get sourceText => switch (source) { 'task' => '下载', 'subscription' => '订阅', 'live' => '直播', _ => source };

  factory LogEntry.fromJson(Map<String, dynamic> j) => LogEntry(_str(j['source']), _str(j['title']), _str(j['message']), _str(j['time']));
}

// ---- formatting ---------------------------------------------------------------------------------------------------

const kIntervals = [
  (3600, '每小时'), (7200, '每 2 小时'), (14400, '每 4 小时'), (28800, '每 8 小时'), (43200, '每 12 小时'), (86400, '每天'), (0, '暂停自动检查'),
];

String intervalLabel(num seconds) {
  for (final (value, label) in kIntervals) {
    if (value == seconds.round()) return label;
  }
  final hours = seconds / 3600;
  return hours == hours.roundToDouble() ? '每 ${hours.round()} 小时' : '每 ${(seconds / 60).round()} 分钟';
}

String formatBytes(num bytes) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  var value = bytes.toDouble(), unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return '${value >= 100 || unit == 0 ? value.toStringAsFixed(0) : value.toStringAsFixed(1)} ${units[unit]}';
}

/// "3 分钟前" / "2 小时后" for an ISO timestamp; [now] is injectable for tests.
String relativeTime(String? iso, {bool future = false, DateTime? now}) {
  if (iso == null || iso.isEmpty) return '尚未检查';
  if (iso == 'pending') return '即将进行';
  final then = DateTime.tryParse(iso);
  if (then == null) return '—';
  final diff = (future ? then.difference(now ?? DateTime.now()) : (now ?? DateTime.now()).difference(then)).inSeconds;
  if (diff < 45) return future ? '即将' : '刚刚';
  for (final (size, name) in [(86400, '天'), (3600, '小时'), (60, '分钟')]) {
    if (diff >= size) return future ? '${(diff / size).round()} $name后' : '${(diff / size).round()} $name前';
  }
  return '刚刚';
}

// ---- live ---------------------------------------------------------------------------------------------------------

class LiveRoom {
  LiveRoom({
    required this.id, required this.platform, required this.name, required this.roomUrl, required this.monitorEnabled, required this.autoRecord,
    required this.recording, required this.monitorAvailable, required this.recordingAvailable, this.isLive, this.checkedAt, this.reason, this.error,
  });

  final String id, platform, name, roomUrl;
  final bool monitorEnabled, autoRecord, recording, monitorAvailable, recordingAvailable;

  /// Result of the last check: true / false, null = never checked.
  final bool? isLive;
  final String? checkedAt, reason, error;

  String get stateText {
    if (recording) return '录制中';
    if (isLive == true) return '直播中';
    if (isLive == false) return '未开播';
    return '尚未检测';
  }

  factory LiveRoom.fromJson(Map<String, dynamic> j) {
    final runtime = _obj(j['runtime']), last = j['last_detection'] is Map ? _obj(j['last_detection']) : null;
    final anchor = _str(j['anchor_name']);
    return LiveRoom(
        id: j['id'] as String, platform: _str(j['platform']), name: anchor.isEmpty ? _str(j['room_url']) : anchor, roomUrl: _str(j['room_url']),
        monitorEnabled: j['monitor_enabled'] != false, autoRecord: j['auto_record'] != false, recording: runtime['recording'] == true,
        monitorAvailable: runtime['monitor_available'] == true, recordingAvailable: runtime['recording_available'] == true,
        isLive: last == null ? null : last['is_live'] as bool?, checkedAt: last?['checked_at'] as String?, reason: runtime['reason'] as String?,
        error: (runtime['recording_error'] ?? runtime['error']) as String?);
  }
}

class LiveRecord {
  LiveRecord(this.id, this.status, this.startTime, this.duration, this.size, this.error);

  final String id, status, startTime, error;
  final num duration;
  final int size;

  String get statusText => switch (status) { 'recording' => '录制中', 'completed' => '已完成', 'failed' => '失败', 'stopped' => '已停止', _ => status };

  factory LiveRecord.fromJson(Map<String, dynamic> j) =>
      LiveRecord(_str(j['id']), _str(j['status']), _str(j['start_time']), _num(j['duration']) ?? 0, _int(j['file_size']), _str(j['error']));
}

/// 3725 -> '1:02:05', 75 -> '1:15'.
String formatClock(num seconds) {
  final total = seconds.round();
  if (total <= 0) return '0:00';
  final h = total ~/ 3600, m = (total % 3600) ~/ 60, s = total % 60;
  final tail = '${m.toString().padLeft(h > 0 ? 2 : 1, '0')}:${s.toString().padLeft(2, '0')}';
  return h > 0 ? '$h:$tail' : tail;
}

// ---- gallery ------------------------------------------------------------------------------------------------------

/// Pictures of a picture post in display order, and its background music if it has one. Ids are asset ids.
class Gallery {
  Gallery(this.images, this.audio, this.index);

  final List<String> images;
  final String? audio;
  final int index;

  factory Gallery.fromJson(Map<String, dynamic> j) => Gallery(
      [for (final raw in (j['images'] as List? ?? const [])) if (raw is Map && raw['id'] is String) raw['id'] as String],
      j['audio'] is Map ? (j['audio'] as Map)['id'] as String? : null,
      _int(j['index']));
}
