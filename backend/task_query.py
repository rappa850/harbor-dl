"""Server-side task pagination and filters."""
from .task_status import ACTIVE, ALL


class TaskQuery:
    def __init__(self, store, assets):
        self.store, self.assets = store, assets

    def list(self, limit=24, offset=0, status='', platform='', subscription_id='',
             manual_only=False, orphan_only=False, query=''):
        conditions, values = [], []
        aliases = {'active': ACTIVE, 'completed': ('COMPLETED',),
                   'error': ('ERROR',), 'cancelled': ('CANCELLED',)}
        if status and status != 'all':
            states = aliases.get(status.lower()) or ((status.upper(),) if status.upper() in ALL else None)
            if states is None:
                raise ValueError('无效的任务状态')
            conditions.append('status IN (' + ','.join('?' for _ in states) + ')')
            values.extend(states)
        if platform and platform != 'all':
            conditions.append('lower(source)=?'); values.append(platform.lower())
        if subscription_id:
            conditions.append('subscription_id=?'); values.append(subscription_id)
        if manual_only:
            conditions.append("(subscription_id IS NULL OR subscription_id='')")
        if query:
            conditions.append("(instr(casefold(title),?)>0 OR instr(casefold(COALESCE(file_path,'')),?)>0 "
                              "OR instr(casefold(author),?)>0)")
            values.extend([query.casefold()] * 3)
        where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
        with self.store.connect() as db:
            db.execute('BEGIN')
            if orphan_only:
                rows = [dict(row) for row in db.execute('SELECT * FROM tasks' + where +
                        ' ORDER BY created_at DESC,id DESC', values)]
                rows = [row for row in rows if self.missing(row)]
                total, items = len(rows), rows[offset:offset+limit]
            else:
                total = db.execute('SELECT COUNT(*) FROM tasks' + where, values).fetchone()[0]
                items = [dict(row) for row in db.execute('SELECT * FROM tasks' + where +
                         ' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?', (*values,limit,offset))]
        return {'items': items, 'tasks': items, 'total': total, 'limit': limit, 'offset': offset}

    def missing(self, task):
        if not task['file_path']:
            return False
        try:
            self.assets.path(task['file_path'])
            return False
        except ValueError:
            return True
