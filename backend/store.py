"""Small transactional store. Each operation owns its connection."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                    expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL,
                    status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
                    downloaded INTEGER NOT NULL DEFAULT 0,
                    total INTEGER NOT NULL DEFAULT 0, speed TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '', file_path TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS tasks_status ON tasks(status);
                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY, task_id TEXT NOT NULL,
                    status TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS platform_cookies (
                    platform TEXT PRIMARY KEY, content TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS media_assets (
                    id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, task_id TEXT,
                    title TEXT NOT NULL, kind TEXT NOT NULL, is_primary INTEGER NOT NULL,
                    created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS media_assets_task ON media_assets(task_id);
                CREATE TABLE IF NOT EXISTS playback_records (
                    subscription_id TEXT PRIMARY KEY, current_index INTEGER NOT NULL DEFAULT 0,
                    playback_mode TEXT NOT NULL DEFAULT 'order', video_progress TEXT NOT NULL DEFAULT '{}',
                    last_updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS api_tokens (
                    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL,
                    token_hash TEXT UNIQUE NOT NULL, token_suffix TEXT NOT NULL,
                    created_at REAL NOT NULL, expires_at REAL, last_used_at REAL,
                    is_active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id TEXT PRIMARY KEY, identity TEXT UNIQUE NOT NULL, config TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS live_subscriptions (
                    id TEXT PRIMARY KEY, identity TEXT UNIQUE NOT NULL, config TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS live_room_states (
                    subscription_id TEXT PRIMARY KEY, result TEXT NOT NULL, checked_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS live_records (
                    id TEXT PRIMARY KEY, subscription_id TEXT NOT NULL, platform TEXT NOT NULL,
                    anchor_name TEXT NOT NULL, room_id TEXT NOT NULL, quality TEXT NOT NULL,
                    status TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT,
                    duration REAL NOT NULL DEFAULT 0, file_size INTEGER NOT NULL DEFAULT 0,
                    file_path TEXT NOT NULL, error TEXT NOT NULL DEFAULT '');
                CREATE INDEX IF NOT EXISTS live_records_scope ON live_records(subscription_id,start_time);
                CREATE TABLE IF NOT EXISTS subscription_videos (
                    id TEXT PRIMARY KEY, subscription_id TEXT NOT NULL, video_id TEXT NOT NULL,
                    metadata TEXT NOT NULL, downloaded INTEGER NOT NULL DEFAULT 0,
                    download_task_id TEXT, error_message TEXT, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, UNIQUE(subscription_id,video_id));
                CREATE TABLE IF NOT EXISTS subscription_states (
                    subscription_id TEXT PRIMARY KEY, last_checked_at TEXT, last_success_at TEXT,
                    last_error TEXT, last_mode TEXT, last_new_count INTEGER NOT NULL DEFAULT 0,
                    last_queued_count INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
                INSERT OR IGNORE INTO settings VALUES ('concurrency', '2');
                PRAGMA user_version=1;
            """)
            columns = {row['name'] for row in db.execute('PRAGMA table_info(tasks)')}
            for name, definition in {'format_id': "TEXT NOT NULL DEFAULT 'bestvideo+bestaudio/best'",
                                     'subtitles': 'INTEGER NOT NULL DEFAULT 1',
                                     'thumbnail': 'INTEGER NOT NULL DEFAULT 1',
                                     'author': "TEXT NOT NULL DEFAULT ''",
                                     'subscription_id': 'TEXT',
                                     'source': "TEXT NOT NULL DEFAULT 'universal'"}.items():
                if name not in columns:
                    db.execute(f'ALTER TABLE tasks ADD COLUMN {name} {definition}')
            video_columns={row['name'] for row in db.execute('PRAGMA table_info(subscription_videos)')}
            if 'download_file_path' not in video_columns:
                db.execute('ALTER TABLE subscription_videos ADD COLUMN download_file_path TEXT')
            db.execute('PRAGMA user_version=15')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.create_function('casefold', 1, lambda value: (value or '').casefold(), deterministic=True)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def all(self, sql, values=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, values).fetchall()]

    def one(self, sql, values=()):
        rows = self.all(sql, values)
        return rows[0] if rows else None
