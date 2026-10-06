"""One-time-visible API tokens with expiry, owner management and rotation."""
import hashlib
import secrets
import time
import uuid
from datetime import datetime, timezone


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


class ApiTokens:
    def __init__(self, store):
        self.store = store

    def view(self, row):
        return {key: timestamp(row[key]) if key in ('created_at','expires_at','last_used_at') else
                bool(row[key]) if key=='is_active' else row[key]
                for key in ('id','name','token_suffix','created_at','expires_at','last_used_at','is_active')}

    def list(self, user_id):
        return [self.view(row) for row in self.store.all('SELECT * FROM api_tokens WHERE user_id=? ORDER BY created_at DESC,id', (user_id,))]

    def create(self, user_id, name, days):
        token = 'harbor_' + secrets.token_urlsafe(40)
        token_id = str(uuid.uuid4())
        created = time.time()
        try:
            expiry = created + days*86400 if days is not None else None
            timestamp(expiry)
        except (ValueError, OverflowError, OSError) as exc:
            raise ValueError('过期时间超出可用范围') from exc
        with self.store.connect() as db:
            db.execute('INSERT INTO api_tokens VALUES (?,?,?,?,?,?,?,?,?)',
                       (token_id, user_id, name, hashlib.sha256(token.encode()).hexdigest(), token[-8:], created, expiry, None, 1))
        return {**self.get(token_id,user_id), 'token':token}

    def get(self, token_id, user_id):
        row = self.store.one('SELECT * FROM api_tokens WHERE id=? AND user_id=?',(token_id,user_id))
        return self.view(row) if row else None

    def update(self, token_id, user_id, fields):
        values = {}
        if 'name' in fields: values['name']=fields['name']
        if 'is_active' in fields: values['is_active']=int(fields['is_active'])
        if 'expires_at' in fields: values['expires_at']=fields['expires_at'].timestamp() if fields['expires_at'] else None
        if values:
            with self.store.connect() as db:
                db.execute('UPDATE api_tokens SET '+','.join(key+'=?' for key in values)+' WHERE id=? AND user_id=?',
                           (*values.values(),token_id,user_id))
        return self.get(token_id,user_id)

    def rotate(self, token_id, user_id):
        token='harbor_'+secrets.token_urlsafe(40)
        with self.store.connect() as db:
            changed=db.execute('UPDATE api_tokens SET token_hash=?,token_suffix=? WHERE id=? AND user_id=?',
                (hashlib.sha256(token.encode()).hexdigest(),token[-8:],token_id,user_id)).rowcount
        return {**self.get(token_id,user_id),'token':token} if changed else None

    def delete(self, token_id, user_id):
        with self.store.connect() as db:
            return bool(db.execute('DELETE FROM api_tokens WHERE id=? AND user_id=?',(token_id,user_id)).rowcount)

    def authenticate(self, token):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            account=db.execute('SELECT u.id,u.username,t.id AS token_id FROM api_tokens t JOIN users u ON u.id=t.user_id '
                'WHERE t.token_hash=? AND t.is_active=1 AND (t.expires_at IS NULL OR t.expires_at>?)',
                (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
            if not account:return None
            db.execute('UPDATE api_tokens SET last_used_at=? WHERE id=?',(time.time(),account['token_id']))
            return {'id':account['id'],'username':account['username']}
