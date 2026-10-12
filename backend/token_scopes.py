"""Permission levels for API tokens. A browser session is the owner and is never restricted.

read      watch, browse and keep personal state (favorites, history, playback position)
download  read + queue downloads, check or sync subscriptions, retry or cancel tasks
manage    everything else (create or change subscriptions, delete, settings, cookies, library export, live)
"""
import re

SCOPES = ('read', 'download', 'manage')
LEVEL = {name: index for index, name in enumerate(SCOPES)}
DEFAULT_SCOPE = 'manage'          # tokens created before scopes existed, and tokens made from the web page

PERSONAL = re.compile(r'^/api/(favorites/[^/]+|history|playback/record/[^/]+)$')
DOWNLOAD = re.compile(r'^/api/(tasks|media/parse|tasks/[^/]+/(cancel|retry)|'
                      r'subscriptions/[^/]+/(check|sync|videos/download|videos/[^/]+/download))$')
SENSITIVE_READ = re.compile(r'^/api/(backup/|network|logs|browser|settings)')


def required(method, path):
    """Lowest scope allowed to call method + path."""
    method = method.upper()
    if method in ('GET', 'HEAD', 'OPTIONS'):
        return 'manage' if SENSITIVE_READ.match(path) else 'read'
    if PERSONAL.match(path):
        return 'read'
    if method == 'POST' and DOWNLOAD.match(path):
        return 'download'
    return 'manage'


def allows(scope, method, path):
    return LEVEL.get(scope, -1) >= LEVEL[required(method, path)]
