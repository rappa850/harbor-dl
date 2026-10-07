"""Remembered media durations, for videos that carry none in their subscription metadata (manual downloads)."""
import shutil
import subprocess

from .downloads import now

PER_PAGE = 8


def read_duration(path):
    executable = shutil.which('ffprobe')
    if not executable:
        return None
    try:
        done = subprocess.run([executable, '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)],
                              capture_output=True, timeout=10, text=True)
        value = float(done.stdout.strip().splitlines()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None
    return value if value > 0 else None


class Probe:
    def __init__(self, store, assets, reader=read_duration):
        self.store, self.assets, self.reader = store, assets, reader

    def durations(self, rows):
        """{asset id: seconds} for rows that have no duration of their own. Probes at most PER_PAGE new files per call and
        remembers the outcome, including "unknown", so a file is never probed twice."""
        wanted = [r for r in rows if r['duration'] is None]
        if not wanted:
            return {}
        known = {r['asset_id']: r['duration'] for r in self.store.all(
            f"SELECT asset_id,duration FROM media_probe WHERE asset_id IN ({','.join('?' * len(wanted))})",
            tuple(r['id'] for r in wanted))}
        fresh = {}
        for row in wanted:
            if row['id'] in known or len(fresh) >= PER_PAGE:
                continue
            try:
                fresh[row['id']] = self.reader(self.assets.path(row['path']))
            except ValueError:
                continue
        if fresh:
            with self.store.connect() as db:
                db.executemany('INSERT OR REPLACE INTO media_probe VALUES (?,?,?)',
                               [(k, v, now()) for k, v in fresh.items()])
        return {k: v for k, v in {**known, **fresh}.items() if v}
