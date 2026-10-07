import json
import tempfile
import unittest
from fastapi.testclient import TestClient
from backend.app import create_app


class FailureLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(self.temp.name)
        self.client = TestClient(self.app)
        self.client.post('/api/setup', json={'username': 'admin', 'password': 'test-password-123'})
        with self.app.state.store.connect() as db:
            for tid, status, error, at in [('t1', 'ERROR', 'HTTP 403 被拒绝', '2026-10-07T01:00:00'),
                                           ('t2', 'ERROR', '', '2026-10-07T03:00:00'),
                                           ('t3', 'COMPLETED', '', '2026-10-07T04:00:00')]:
                db.execute('INSERT INTO tasks(id,url,title,status,error,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
                           (tid, 'https://example.com/' + tid, 'video ' + tid, status, error, at, at))
            db.execute('INSERT INTO subscriptions VALUES (?,?,?,?,?)',
                       ('s1', 'x:1', json.dumps({'user_id': 'u1', 'nickname': '小明'}), 'a', 'a'))
            db.execute('INSERT INTO subscriptions VALUES (?,?,?,?,?)',
                       ('s2', 'x:2', json.dumps({'user_id': 'u2', 'nickname': ''}), 'a', 'a'))
            db.execute("INSERT INTO subscription_states(subscription_id,last_checked_at,last_error,updated_at) VALUES ('s1','2026-10-07T02:00:00','风控 403','a')")
            db.execute("INSERT INTO subscription_states(subscription_id,last_checked_at,last_error,updated_at) VALUES ('s2','2026-10-07T02:30:00',NULL,'a')")
            db.execute("INSERT INTO live_records VALUES ('r1','l1','bilibili','主播甲','100','原画','failed','2026-10-07T05:00:00',NULL,0,0,'f.ts','')")
            db.execute("INSERT INTO live_records VALUES ('r2','l1','bilibili','主播甲','100','原画','completed','2026-10-07T06:00:00',NULL,0,0,'g.ts','')")

    def tearDown(self):
        self.client.close(); self.temp.cleanup()

    def test_merges_only_failures_newest_first(self):
        data = self.client.get('/api/logs').json()
        self.assertEqual([(i['source'], i['ref']) for i in data['items']],
                         [('live', 'r1'), ('task', 't2'), ('subscription', 's1'), ('task', 't1')])
        self.assertEqual(data['counts'], {'task': 2, 'subscription': 1, 'live': 1})
        self.assertEqual(data['total'], 4)

    def test_titles_and_fallback_messages(self):
        by_ref = {i['ref']: i for i in self.client.get('/api/logs').json()['items']}
        self.assertEqual(by_ref['s1']['title'], '小明')
        self.assertIn('没有记录详细原因', by_ref['t2']['message'])
        self.assertIn('没有记录详细原因', by_ref['r1']['message'])

    def test_source_filter_search_and_paging(self):
        self.assertEqual(self.client.get('/api/logs?source=task').json()['total'], 2)
        self.assertEqual([i['ref'] for i in self.client.get('/api/logs?query=403').json()['items']], ['s1', 't1'])
        page = self.client.get('/api/logs?limit=1&offset=1').json()
        self.assertEqual((page['total'], [i['ref'] for i in page['items']]), (4, ['t2']))
        self.assertEqual(self.client.get('/api/logs?source=bogus').status_code, 422)

    def test_requires_login(self):
        with TestClient(self.app) as anonymous:
            self.assertEqual(anonymous.get('/api/logs').status_code, 401)


if __name__ == '__main__':
    unittest.main()
