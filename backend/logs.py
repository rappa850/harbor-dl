"""Failure log: one read-only view over the failures the app already records.

There is no separate log table. Failed downloads, the last error of each subscription sync and failed live
recordings are persisted by their own modules; this joins them so the UI can show and search them in one place.
"""
SOURCES = ('task', 'subscription', 'live')

_UNION = """
    SELECT 'task' AS source, id AS ref, title, COALESCE(NULLIF(error,''),'下载失败（没有记录详细原因）') AS message,
           updated_at AS time FROM tasks WHERE status='ERROR'
    UNION ALL
    SELECT 'subscription', s.id,
           COALESCE(NULLIF(json_extract(s.config,'$.nickname'),''), json_extract(s.config,'$.user_id'), s.id),
           st.last_error, COALESCE(st.last_checked_at, st.updated_at)
    FROM subscription_states st JOIN subscriptions s ON s.id=st.subscription_id
    WHERE COALESCE(st.last_error,'')<>''
    UNION ALL
    SELECT 'live', id, COALESCE(NULLIF(anchor_name,''), room_id),
           COALESCE(NULLIF(error,''),'录制失败（没有记录详细原因）'), COALESCE(end_time, start_time)
    FROM live_records WHERE status='failed'
"""


class FailureLog:
    def __init__(self, store):
        self.store = store

    def list(self, source='', query='', limit=50, offset=0):
        if source and source not in SOURCES:
            raise ValueError('无效的日志来源')
        conditions, values = [], []
        if source:
            conditions.append('source=?'); values.append(source)
        if query:
            conditions.append('(instr(casefold(title),?)>0 OR instr(casefold(message),?)>0)')
            values.extend([query.casefold()] * 2)
        where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
        base = f'SELECT * FROM ({_UNION}){where}'
        with self.store.connect() as db:
            db.execute('BEGIN')
            total = db.execute(f'SELECT COUNT(*) FROM ({base})', values).fetchone()[0]
            items = [dict(row) for row in db.execute(f'{base} ORDER BY time DESC, ref LIMIT ? OFFSET ?',
                                                     [*values, limit, offset])]
            counts = {row['source']: row['n'] for row in db.execute(
                f'SELECT source, COUNT(*) AS n FROM ({_UNION}) GROUP BY source')}
        return {'items': items, 'total': total, 'counts': {name: counts.get(name, 0) for name in SOURCES}}
