"""Persistent platform cookies and explicit proxy routing for media adapters."""
import fnmatch
import http.cookiejar
import json
import re
import tempfile
import warnings
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .media import platform_for

PLATFORMS = ('youtube', 'bilibili', 'douyin', 'xiaohongshu', 'kuaishou', 'tiktok',
             'instagram', 'x', 'netease', 'universal', 'sooplive', 'pandatv')
DEFAULT = {'enabled': False, 'proxy': '', 'no_proxy': 'localhost,127.0.0.1,*.local'}


@contextmanager
def cookie_file(content, url):
    """Convert header cookies into domain-bound Netscape cookies; never log values."""
    with tempfile.TemporaryDirectory(prefix='harbor-cookie-') as folder:
        target = Path(folder) / 'cookies.txt'
        if '# Netscape HTTP Cookie File' in content or '# HTTP Cookie File' in content:
            target.write_text(content, encoding='utf-8')
            jar = http.cookiejar.MozillaCookieJar(str(target))
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    jar.load(ignore_discard=True, ignore_expires=True)
            except (http.cookiejar.LoadError, ValueError, OSError) as exc:
                raise ValueError('Netscape Cookie 文件格式无效') from exc
            if not list(jar):
                raise ValueError('Cookie 文件没有有效条目')
        else:
            if '\n' in content or '\r' in content:
                raise ValueError('Cookie 请求头必须为单行')
            host = urlsplit(url).hostname
            if not host:
                raise ValueError('Cookie 缺少适用域名')
            lines = ['# Netscape HTTP Cookie File']
            for item in content.removeprefix('Cookie:').strip().split(';'):
                if not item.strip():
                    continue
                name, separator, value = item.strip().partition('=')
                if not separator or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) or '\t' in value:
                    raise ValueError('Cookie 请求头格式无效')
                lines.append('\t'.join([host, 'FALSE', '/', 'TRUE' if url.startswith('https:') else 'FALSE', '0', name, value]))
            if len(lines) == 1:
                raise ValueError('Cookie 不能为空')
            target.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        yield str(target)


def validate_proxy(value):
    if not value:
        return ''
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https', 'socks5', 'socks5h') or not parsed.hostname or not parsed.port:
            raise ValueError()
        if parsed.path not in ('', '/') or parsed.query or parsed.fragment or any(c in value for c in '\r\n\t '):
            raise ValueError()
    except ValueError as exc:
        raise ValueError('代理需使用 http、https 或 socks5 URL，并包含端口') from exc
    return value


def proxy_display(value):
    parsed = urlsplit(value)
    host = parsed.hostname or ''
    if ':' in host:
        host = '[' + host + ']'
    return f'{parsed.scheme}://{host}:{parsed.port}' if value else ''


class NetworkConfig:
    def __init__(self, store):
        self.store = store

    def config(self):
        row = self.store.one('SELECT value FROM settings WHERE key=?', ('network',))
        return {**DEFAULT, **json.loads(row['value'])} if row else dict(DEFAULT)

    def status(self):
        config = self.config()
        cookies = {name: {'exists': False} for name in PLATFORMS}
        for row in self.store.all('SELECT platform,length(content) AS size,updated_at FROM platform_cookies'):
            cookies[row['platform']] = {'exists': True, 'size': row['size'], 'updated_at': row['updated_at']}
        return {'enabled': config['enabled'], 'proxy_display': proxy_display(config['proxy']),
                'has_proxy': bool(config['proxy']), 'no_proxy': config['no_proxy'], 'cookies': cookies}

    def save_proxy(self, enabled, proxy, no_proxy):
        config = self.config()
        value = validate_proxy(proxy) if proxy is not None else config['proxy']
        if enabled and not value:
            raise ValueError('启用代理时需填写代理地址')
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)',
                       ('network', json.dumps({'enabled': enabled, 'proxy': value, 'no_proxy': no_proxy})))
        return self.status()

    def save_cookie(self, platform, content):
        if platform not in PLATFORMS:
            raise ValueError('不支持的平台配置')
        content = content.strip()
        with cookie_file(content, 'https://validation.invalid/'):
            pass
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO platform_cookies VALUES (?,?,?)', (platform, content, datetime.now(timezone.utc).isoformat()))
        return self.status()

    def clear_cookie(self, platform):
        if platform not in PLATFORMS:
            raise ValueError('不支持的平台配置')
        with self.store.connect() as db:
            db.execute('DELETE FROM platform_cookies WHERE platform=?', (platform,))
        return self.status()

    def for_url(self, url):
        config = self.config()
        host = urlsplit(url).hostname or ''
        bypass = any(fnmatch.fnmatchcase(host, entry.strip()) or host == entry.strip().lstrip('.') or
                     (entry.strip().startswith('.') and host.endswith(entry.strip()))
                     for entry in config['no_proxy'].split(',') if entry.strip())
        cookie = self.store.one('SELECT content FROM platform_cookies WHERE platform=?', (platform_for(url),))
        return {'proxy': config['proxy'] if config['enabled'] and not bypass else '',
                'cookie_content': cookie['content'] if cookie else ''}


def redact(message, network):
    value = str(message)
    proxy = network.get('proxy', '')
    if proxy:
        value = value.replace(proxy, '[代理地址]')
        credentials = urlsplit(proxy)
        for secret in (credentials.username, credentials.password):
            if secret:
                value = value.replace(secret, '[已隐藏]')
                value = value.replace(unquote(secret), '[已隐藏]')
    content = network.get('cookie_content', '')
    if content:
        value = value.replace(content, '[Cookie 已隐藏]')
        for line in content.splitlines():
            if '\t' in line and (not line.startswith('#') or line.startswith('#HttpOnly_')):
                parts = line.split('\t')
                secret = parts[-1] if len(parts) == 7 else ''
                if secret:
                    value = value.replace(secret, '[已隐藏]')
        if '\t' not in content:
            for part in content.split(';'):
                _, sep, secret = part.partition('=')
                if sep and secret.strip():
                    value = value.replace(secret.strip(), '[已隐藏]')
    return value
