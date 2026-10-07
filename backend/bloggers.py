"""Bloggers (authors) of the downloaded library, enriched with the profile stored on their subscription.

A blogger is the author name recorded on the downloaded tasks; the subscription with the same nickname, when there is
one, supplies avatar, signature and follower count. A blogger is listed when they have a playable video or at least
one synced subscription work; works that are not downloaded yet are reported separately (`remote`) and never enter the
playable feed.
"""
import json

SORTS = ('recent', 'count', 'name')


class Bloggers:
    def __init__(self, feed, store, covers, prefetch=None, catalog=None):
        self.feed, self.store, self.covers, self.prefetch, self.catalog = feed, store, covers, prefetch, catalog

    def _remote(self):
        """{author: works} for synced works whose file is not available (not downloaded, downloading, failed...)."""
        found = {}
        if not self.catalog:
            return found
        for row in self.store.all('SELECT id,config FROM subscriptions ORDER BY created_at'):
            try:
                name = (json.loads(row['config']).get('nickname') or '').strip()
                records = self.catalog.records(row['id'])
            except (ValueError, LookupError):
                continue
            if not name:
                continue
            for record in records:
                if record['status'] == 'downloaded':
                    continue
                found.setdefault(name, []).append({
                    'id': record['id'], 'subscription_id': record['subscription_id'], 'title': record.get('title') or '',
                    'cover': record.get('cover_local'), 'duration': record.get('duration'),
                    'published': record.get('publish_time') or '', 'status': record['status']})
        for works in found.values():
            works.sort(key=lambda w: w['published'], reverse=True)
        return found

    def works(self, author):
        return self._remote().get(author, [])

    def _profiles(self):
        profiles = {}
        for row in self.store.all('SELECT config FROM subscriptions ORDER BY created_at'):
            try:
                config = json.loads(row['config'])
            except ValueError:
                continue
            name = (config.get('nickname') or '').strip()
            # several subscriptions may share a nickname; keep the one that actually has an avatar
            if name and (name not in profiles or (config.get('avatar_url') and not profiles[name].get('avatar_url'))):
                profiles[name] = config
        return profiles

    def _groups(self):
        groups = {}
        for row in self.feed._playable(''):
            if not row['author']:
                continue
            group = groups.setdefault(row['author'], {'count': 0, 'latest': ''})
            group['count'] += 1
            group['latest'] = max(group['latest'], row['created_at'] or '')
        return groups

    def _item(self, name, group, profile, remote=()):
        profile = profile or {}
        avatar_url = profile.get('avatar_url')
        avatar = self.covers.local(avatar_url) if avatar_url else None
        if avatar_url and not avatar and self.prefetch:
            self.prefetch(avatar_url)  # shows up on the next request; the app falls back to the initial meanwhile
        return {'author': name, 'count': group['count'], 'remote': len(remote),
                'latest_at': max(group['latest'], *(w['published'] for w in remote), ''), 'avatar': avatar,
                'signature': profile.get('signature') or '', 'platform': profile.get('platform') or '',
                'followers': profile.get('follower_count')}

    def list(self, query='', sort='recent'):
        if sort not in SORTS:
            raise ValueError('无效的排序方式')
        profiles, needle, remote = self._profiles(), query.strip().casefold(), self._remote()
        groups = self._groups()
        names = set(groups) | set(remote)
        items = [self._item(name, groups.get(name, {'count': 0, 'latest': ''}), profiles.get(name), remote.get(name, ()))
                 for name in names if not needle or needle in name.casefold()]
        if sort == 'recent':
            items.sort(key=lambda i: (i['latest_at'], i['author']), reverse=True)
        elif sort == 'count':
            items.sort(key=lambda i: (-i['count'], i['author']))
        else:
            items.sort(key=lambda i: i['author'].casefold())
        return items

    def get(self, author):
        groups, remote = self._groups(), self._remote()
        if author not in groups and author not in remote:
            return None
        return self._item(author, groups.get(author, {'count': 0, 'latest': ''}), self._profiles().get(author),
                          remote.get(author, ()))
