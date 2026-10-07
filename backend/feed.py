"""Paged video feed for the mobile app: one flat, stable ordering over the playable library."""
import base64
import hashlib
import json

MODES = ('latest', 'random', 'favorites', 'history')
MAX_LIMIT = 50

_VIDEOS = """
    SELECT a.id, a.title, a.path, a.created_at, a.task_id, t.url AS work_url, t.author, t.source,
           t.subscription_id,
           (SELECT json_extract(v.metadata,'$.duration') FROM subscription_videos v
            WHERE v.download_task_id=a.task_id LIMIT 1) AS duration
    FROM media_assets a LEFT JOIN tasks t ON t.id=a.task_id
    WHERE a.kind='video'
"""


def encode_cursor(offset):
    return base64.urlsafe_b64encode(json.dumps({'o': offset}).encode()).decode().rstrip('=')


def decode_cursor(cursor):
    if not cursor:
        return 0
    try:
        offset = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))['o']
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError('无效的游标') from exc
    if not isinstance(offset, int) or offset < 0:
        raise ValueError('无效的游标')
    return offset


class Feed:
    def __init__(self, store, assets, covers, key_for):
        self.store, self.assets, self.covers, self.key_for = store, assets, covers, key_for

    def _playable(self, author):
        rows = []
        for row in self.store.all(_VIDEOS + (' AND t.author=?' if author else ''), (author,) if author else ()):
            try:
                self.assets.path(row['path'])
            except ValueError:
                continue
            rows.append(row)
        return rows

    def authors(self):
        counts = {}
        for row in self._playable(''):
            if row['author']:
                counts[row['author']] = counts.get(row['author'], 0) + 1
        return sorted(({'author': name, 'count': n} for name, n in counts.items()),
                      key=lambda a: (-a['count'], a['author']))

    def page(self, user_id, cursor='', limit=20, mode='latest', seed='', author=''):
        if mode not in MODES:
            raise ValueError('无效的排序方式')
        offset, limit = decode_cursor(cursor), max(1, min(limit, MAX_LIMIT))
        favorites = {r['asset_id']: r['created_at'] for r in
                     self.store.all('SELECT asset_id,created_at FROM favorites WHERE user_id=?', (user_id,))}
        history = {r['asset_id']: r for r in
                   self.store.all('SELECT asset_id,position,watched_at FROM watch_history WHERE user_id=?', (user_id,))}
        rows = self._playable(author)
        if mode == 'favorites':
            rows = sorted((r for r in rows if r['id'] in favorites), key=lambda r: favorites[r['id']], reverse=True)
        elif mode == 'history':
            rows = sorted((r for r in rows if r['id'] in history), key=lambda r: history[r['id']]['watched_at'], reverse=True)
        elif mode == 'random':
            # a fixed seed keeps the order stable across pages; a new seed reshuffles
            rows.sort(key=lambda row: hashlib.sha1(f"{seed}:{row['id']}".encode()).hexdigest())
        else:
            rows.sort(key=lambda row: (row['created_at'] or '', row['path']), reverse=True)
        chunk = rows[offset:offset + limit]
        more = offset + limit < len(rows)
        return {'items': [self._item(row, row['id'] in favorites, history.get(row['id'])) for row in chunk], 'total': len(rows),
                'next': encode_cursor(offset + limit) if more else None}

    def _item(self, row, favorite=False, seen=None):
        return {'favorite': favorite, 'position': seen['position'] if seen else 0,
                'id': row['id'], 'kind': 'video', 'title': row['title'], 'author': row['author'] or '',
                'source': row['source'], 'subscription_id': row['subscription_id'],
                'duration': row['duration'], 'created_at': row['created_at'],
                'cover': self.covers.local(row['work_url']) or f"/api/files/{row['id']}/poster",
                'stream': f"/api/files/{row['id']}/stream"}
