"""Bloggers (authors) of the downloaded library, enriched with the profile stored on their subscription.

A blogger is the author name recorded on the downloaded tasks; the subscription with the same nickname, when there is
one, supplies avatar, signature and follower count. Only bloggers with at least one playable video are listed.
"""
import json

SORTS = ('recent', 'count', 'name')


class Bloggers:
    def __init__(self, feed, store, covers, prefetch=None):
        self.feed, self.store, self.covers, self.prefetch = feed, store, covers, prefetch

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

    def _item(self, name, group, profile):
        profile = profile or {}
        avatar_url = profile.get('avatar_url')
        avatar = self.covers.local(avatar_url) if avatar_url else None
        if avatar_url and not avatar and self.prefetch:
            self.prefetch(avatar_url)  # shows up on the next request; the app falls back to the initial meanwhile
        return {'author': name, 'count': group['count'], 'latest_at': group['latest'], 'avatar': avatar,
                'signature': profile.get('signature') or '', 'platform': profile.get('platform') or '',
                'followers': profile.get('follower_count')}

    def list(self, query='', sort='recent'):
        if sort not in SORTS:
            raise ValueError('无效的排序方式')
        profiles, needle = self._profiles(), query.strip().casefold()
        items = [self._item(name, group, profiles.get(name)) for name, group in self._groups().items()
                 if not needle or needle in name.casefold()]
        if sort == 'recent':
            items.sort(key=lambda i: (i['latest_at'], i['author']), reverse=True)
        elif sort == 'count':
            items.sort(key=lambda i: (-i['count'], i['author']))
        else:
            items.sort(key=lambda i: i['author'].casefold())
        return items

    def get(self, author):
        groups = self._groups()
        if author not in groups:
            return None
        return self._item(author, groups[author], self._profiles().get(author))
