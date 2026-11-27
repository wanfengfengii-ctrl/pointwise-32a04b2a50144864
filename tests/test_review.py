from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from http.client import RemoteDisconnected

from tests.scenario import FestivalCase, comment_input, emit, page_input, proof_input


class TestReview(FestivalCase):
    def test_offline_page(self):
        _, bundle = self.scene.prepare(self.sample)
        old_office = self.office
        self.scene.office.stop()
        with self.assertRaises(OSError):
            old_office.request('GET', '/release', query={'round_id': 'R'})
        installed = self.desk.ok('GET', '/install', query={'round_id': 'R'})
        self.assertEqual(installed['bundle'], bundle)
        draft = self.draft('W01', 'B', '第 4 拍同时换气。')
        body = page_input(draft, 'rB')
        page = self.desk.ok('POST', '/page', body=body)
        expected_content = {
            'draft_id': draft['draft_id'], 'release_id': bundle['release_id'], 'round_id': 'R',
            'alias': 'W01', 'reviewer_id': 'B', 'proof_id': bundle['works'][0]['proof_id'],
            'window': [3, 5], 'text': '第 4 拍同时换气。',
        }
        formal = self.desk.ok('GET', '/page', query={'page_id': page['page_id']})
        receipt = self.desk.ok('GET', '/receipt', query={'request_id': 'rB'})
        self.assertEqual(page['draft_id'], draft['draft_id'])
        self.assertEqual(formal, {'page_id': page['page_id'], **expected_content})
        self.assertEqual(receipt, {**formal, 'request_id': 'rB'})
        emit('n4.offline_source', body, {'draft_id': draft['draft_id']}, {'draft_id': page['draft_id']},
             expected_content, {key: formal[key] for key in expected_content},
             ['desk/install.py', 'desk/comments.py', 'desk/pages.py', 'desk/receipts.py'],
             'P 属甲、B 属乙。原发行交段覆盖 [3,5)，正式页使用请求中指定的实际稿件。')

    def test_install_conflict(self):
        _, bundle = self.scene.prepare(self.sample)
        got = self.desk.ok('GET', '/install', query={'round_id': 'R'})
        reordered = dict(reversed(list(bundle.items())))
        reordered['works'] = [dict(reversed(list(work.items()))) for work in bundle['works']]
        self.assertEqual(self.desk.ok('POST', '/install', body=reordered), got)
        altered = deepcopy(bundle)
        altered['works'][0]['spans'][0]['text'] = '另一份文字'
        self.assertEqual(self.desk.request('POST', '/install', body=altered), (409, {'error': 'installed_bundle_conflict'}))
        alternate_issue = {**bundle, 'release_id': 'another-id'}
        self.assertEqual(self.desk.request('POST', '/install', body=alternate_issue), (409, {'error': 'installed_round_conflict'}))
        self.assertEqual(self.desk.ok('GET', '/install', query={'round_id': 'R'}), got)

    def test_gap_window(self):
        proof = proof_input(self.sample, 'P')
        proof['segments'][0]['window'] = [1, 3]
        proof['segments'][1]['window'] = [4, 7]
        proof['window'] = [1, 7]
        _, bundle = self.scene.prepare(self.sample)
        self.scene.office.stop()
        bad = comment_input('R', 'W01', 'B', '跨越中间空拍', [2, 5])
        observed = self.desk.request('POST', '/comment', body=bad)
        self.assertEqual(observed, (422, {'error': 'window_not_covered'}))
        out_of_bounds = {**bad, 'window': [6, 8]}
        self.assertEqual(self.desk.request('POST', '/comment', body=out_of_bounds)[0], 422)
        draft = self.draft('W01', 'B', '只讲第二段', window=[4, 5])
        self.assertEqual(draft['draft_id'], 'draft-1')
        self.assertEqual(draft['proof_id'], bundle['works'][0]['proof_id'])
        issued = self.desk.ok('POST', '/page', body=page_input(draft, 'inside'))
        self.assertEqual(issued['draft_id'], draft['draft_id'])
        emit('n4.gap_window', bad, 422, observed[0], 'draft-1', issued['draft_id'],
             ['issue/payload.py', 'desk/comments.py', 'desk/pages.py'],
             '交段 [1,3) 与 [4,7) 间有 [3,4) 空隙。两次拒绝均不占稿件号。')

    def test_draft_binding(self):
        self.scene.prepare(self.sample)
        p = self.draft('W01', 'C', 'P 的文字')
        q = self.draft('W02', 'C', 'Q 的文字')
        bad_request = {**page_input(p, 'wrong'), 'draft_id': q['draft_id']}
        self.assertEqual(self.desk.request('POST', '/page', body=bad_request), (409, {'error': 'draft_mismatch'}))
        self.assertEqual(self.desk.ok('GET', '/receipts', query={'round_id': 'R'}), {'receipts': []})
        right = self.desk.ok('POST', '/page', body=page_input(p, 'right'))
        self.assertEqual(self.desk.ok('GET', '/page', query={'page_id': right['page_id']})['text'], 'P 的文字')

    def test_same_group(self):
        self.scene.prepare(self.sample)
        same = self.draft('W01', 'A')
        self.assertEqual(self.desk.request('POST', '/page', body=page_input(same, 'same')), (409, {'error': 'not_eligible'}))
        self.assertEqual(self.desk.request('GET', '/receipt', query={'request_id': 'same'})[0], 404)
        self.assertEqual(self.desk.ok('GET', '/receipts', query={'round_id': 'R'}), {'receipts': []})
        cross = self.draft('W01', 'B')
        self.assertEqual(self.desk.ok('POST', '/page', body=page_input(cross, 'cross'))['draft_id'], cross['draft_id'])

    def test_original_receipt(self):
        _, bundle = self.scene.prepare(self.sample)
        installed = self.desk.ok('GET', '/install', query={'round_id': 'R'})
        draft = self.draft('W01', 'B')
        original = page_input(draft, 'original')
        page = self.desk.ok('POST', '/page', body=original)
        unused_draft = self.draft('W01', 'B', '保留这一稿而未采用')
        self.scene.desk.stop()
        self.scene.desk.start()
        self.assertEqual(self.desk.ok('POST', '/install', body=bundle), installed)
        self.assertEqual(self.desk.ok('POST', '/page', body=original), page)
        changed = {**original, 'draft_id': unused_draft['draft_id']}
        self.assertEqual(self.desk.request('POST', '/page', body=changed), (409, {'error': 'page_request_conflict'}))
        other_page = self.desk.ok('POST', '/page', body=page_input(self.draft('W01', 'C'), 'other'))
        self.assertNotEqual(other_page['page_id'], page['page_id'])
        self.assertEqual(self.desk.ok('GET', '/receipt', query={'request_id': 'original'})['draft_id'], draft['draft_id'])

    def test_single_page(self):
        self.scene.prepare(self.sample)
        draft = self.draft('W01', 'B')
        competing = [page_input(draft, request_id) for request_id in ('one', 'two')]
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = [pool.submit(self.desk.request, 'POST', '/page', body=body) for body in competing]
            results = [future.result() for future in pending]
        self.assertEqual(sorted(status for status, _ in results), [200, 409])
        issued = next(value for status, value in results if status == 200)
        declined = next(value for status, value in results if status == 409)
        self.assertEqual(declined, {'error': 'relation_already_issued'})
        receipts = self.desk.ok('GET', '/receipts', query={'round_id': 'R'})['receipts']
        self.assertEqual([item['page_id'] for item in receipts], [issued['page_id']])

    def test_commit_lost_reply(self):
        self.scene.prepare(self.sample)
        original = page_input(self.draft('W01', 'B'), 'lost')
        changed = {**original, 'draft_id': self.draft('W01', 'B', '另一个版本')['draft_id']}
        desk = self.scene.desk
        with ThreadPoolExecutor(max_workers=1) as pool, desk.hold('POST', '/page', phase='after', drop=True) as gate:
            result = pool.submit(self.desk.request, 'POST', '/page', body=original)
            gate.wait_until_held()
            self.assertFalse(result.done())
            committed = self.desk.ok('GET', '/receipt', query={'request_id': 'lost'})
            self.assertEqual(committed['draft_id'], original['draft_id'])
            gate.release()
            with self.assertRaises(RemoteDisconnected):
                result.result()
        desk.stop()
        desk.start()
        recovered = self.desk.ok('POST', '/page', body=original)
        expected = {'page_id': committed['page_id'], 'draft_id': original['draft_id']}
        self.assertEqual(recovered, expected)
        self.assertEqual(self.desk.request('POST', '/page', body=changed)[0], 409)
        retained = self.desk.ok('GET', '/receipts', query={'round_id': 'R'})['receipts']
        self.assertEqual(retained, [committed])
        emit('n6.commit_lost_reply', original, expected, recovered, [committed], retained,
             ['desk/http.py', 'desk/pages.py', 'desk/receipts.py'],
             '首次回包仍扣住时由独立 HTTP 查询取得已提交页号。同库重开后应取回同页且只有一份首执。')

    def test_delayed_request_has_no_formal_page_yet(self):
        self.scene.prepare(self.sample)
        b = page_input(self.draft('W01', 'B'), 'in-flight')
        c = page_input(self.draft('W01', 'C'), 'independent')
        with ThreadPoolExecutor(max_workers=1) as pool, self.scene.desk.hold('POST', '/page', phase='before') as gate:
            result = pool.submit(self.desk.request, 'POST', '/page', body=b)
            gate.wait_until_held()
            self.assertEqual(self.desk.request('GET', '/receipt', query={'request_id': 'in-flight'})[0], 404)
            self.assertEqual(self.desk.ok('POST', '/page', body=c)['draft_id'], c['draft_id'])
            self.assertEqual(self.desk.request('GET', '/receipt', query={'request_id': 'in-flight'})[0], 404)
            gate.release()
            status, page = result.result()
            self.assertEqual((status, page['draft_id']), (200, b['draft_id']))
