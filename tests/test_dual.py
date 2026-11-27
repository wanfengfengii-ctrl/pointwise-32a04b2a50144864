from copy import deepcopy

from tests.scenario import FestivalCase, release_input, receipt_input


def dual_sample(sample):
    """Add a fourth reviewer (D, group 丁) so a 甲 work has three recused people:
    two locked prelim reviewers plus a separate adjudicator."""
    extended = deepcopy(sample)
    extended['reviewers'] = sample['reviewers'] + [{'reviewer_id': 'D', 'group': '丁'}]
    return extended


def dual_release(office, sample, round_id, dual_work='P'):
    sample = dual_sample(sample)
    works = []
    for work in sample['works']:
        proof = office.ok('POST', '/proof', body=work['proof'])
        works.append({'work_id': work['work_id'], 'group': work['group'], 'proof_id': proof['proof_id']})
    target = next(work for work in works if work['work_id'] == dual_work)
    body = {
        'round_id': round_id,
        'works': works,
        'reviewers': sample['reviewers'],
        'dual_review': [
            {'work_id': dual_work, 'prelim_reviewers': ['B', 'C'], 'adjudicator': 'D'}
        ],
    }
    bundle = office.ok('POST', '/release', body=body)
    return body, bundle, target


def prelim_body(round_id, alias, reviewer_id, marks, request_id):
    return {
        'round_id': round_id,
        'alias': alias,
        'reviewer_id': reviewer_id,
        'marks': marks,
        'request_id': request_id,
    }


def decision_body(round_id, alias, adjudicator, window, mark, request_id):
    return {
        'round_id': round_id,
        'alias': alias,
        'adjudicator': adjudicator,
        'window': window,
        'mark': mark,
        'request_id': request_id,
    }


class TestDualReview(FestivalCase):
    def _prepare_dual(self, round_id='RD'):
        body, bundle, target = dual_release(self.office, self.sample, round_id)
        self.desk.ok('POST', '/install', body=bundle)
        alias = next(work['alias'] for work in bundle['works'] if work['proof_id'] == target['proof_id'])
        return body, bundle, alias

    def test_designation_locks_relations_and_is_anonymous(self):
        _, bundle, alias = self._prepare_dual()
        dual = bundle['dual_review']
        self.assertEqual(dual, [{'alias': alias, 'prelim_reviewers': ['B', 'C'], 'adjudicator': 'D'}])
        # 双评作品只锁两位初评；普通作品 W02 仍按跨组资格全开。
        eligible = {(item['alias'], item['reviewer_id']) for item in bundle['eligible']}
        self.assertNotIn((alias, 'A'), eligible)
        self.assertEqual({r for a, r in eligible if a == alias}, {'B', 'C'})
        self.assertIn(('W02', 'A'), eligible)
        self.assertIn(('W02', 'C'), eligible)
        # 匿名件不携带内部作品键。
        self.assertEqual(set(bundle['works'][0]), {'alias', 'proof_id', 'spans'})

    def _make_prelim(self, round_id, alias, reviewer_id, marks, request_id):
        self.desk.ok('POST', '/preliminary',
                     body=prelim_body(round_id, alias, reviewer_id, marks, request_id))
        return self.desk.ok('GET', '/prelim-receipt', query={'request_id': request_id})

    def test_early_decision_parked_then_replayed_and_partial_close(self):
        round_id = 'RD'
        _, bundle, alias = self._prepare_dual(round_id)
        release_id = bundle['release_id']

        # 领评台离线先出齐两页（office 此时尚未收到任何首执）。
        # B 在 [2,6) 全段通过；C 在 [3,5) 返练 => 分歧为相邻的 [3,4)、[4,5)。
        b_marks = [{'window': [2, 4], 'mark': 'pass'}, {'window': [4, 6], 'mark': 'pass'}]
        c_marks = [{'window': [3, 5], 'mark': 'redo'}]
        b_page = self.desk.ok('POST', '/preliminary',
                              body=prelim_body(round_id, alias, 'B', b_marks, 'req-B'))
        b_receipt = self.desk.ok('GET', '/prelim-receipt', query={'request_id': 'req-B'})
        c_receipt = self._make_prelim(round_id, alias, 'C', c_marks, 'req-C')

        # 复核首执先到 office：初评未核，先存待核，无需重送。
        early = decision_body(round_id, alias, 'D', [3, 4], 'pass', 'early-1')
        self.desk.ok('POST', '/decision', body=early)
        early_receipt = self.desk.ok('GET', '/decision', query={'request_id': 'early-1'})
        parked = self.office.ok('POST', '/decision-reconcile',
                                body={'release_id': release_id, 'receipt': early_receipt})
        self.assertTrue(parked['held'])
        dual = parked['dual_review'][0]
        self.assertEqual(dual['alias'], alias)
        self.assertEqual(dual['missing_prelim'], ['B', 'C'])
        self.assertEqual(dual['undecided_windows'], [])

        # 第一张初评：仍欠一张，分歧未出。
        status = self.office.ok('POST', '/prelim-reconcile',
                                body={'release_id': release_id, 'receipt': b_receipt})
        entry = status['dual_review'][0]
        self.assertEqual(entry['missing_prelim'], ['C'])
        self.assertEqual(entry['undecided_windows'], [])

        # 第二张初评：分歧 [3,4) 与 [4,5)；待核首执按实际原页重核（[3,4) 通过有效）。
        status = self.office.ok('POST', '/prelim-reconcile',
                                body={'release_id': release_id, 'receipt': c_receipt})
        entry = status['dual_review'][0]
        self.assertEqual(entry['missing_prelim'], [])
        # [3,4) 已由待核首执裁决，只剩 [4,5)。
        self.assertEqual(entry['undecided_windows'], [[4, 5]])

        # 复核人只看到匿名节选与需复核拍窗。
        view = self.desk.ok('GET', '/dispute', query={'round_id': round_id, 'alias': alias})
        self.assertEqual(view['status'], 'open')
        self.assertEqual(view['windows'], [[4, 5]])
        self.assertEqual(set(view['excerpt']), {'alias', 'proof_id', 'spans'})

        # 不能跨出分歧范围。
        outside = decision_body(round_id, alias, 'D', [5, 6], 'redo', 'outside')
        self.assertEqual(self.desk.request('POST', '/decision', body=outside)[1],
                         {'error': 'outside_dispute_scope'})
        # 同号同参可复领，异参不受理。
        reissued = self.desk.ok('POST', '/decision', body=early)
        self.assertEqual(reissued, {'decision_id': early_receipt['decision_id'], 'request_id': 'early-1'})
        conflict = {**early, 'mark': 'redo'}
        self.assertEqual(self.desk.request('POST', '/decision', body=conflict)[1],
                         {'error': 'decision_request_conflict'})

        # 对剩余子窗裁决，分批且互不重叠。
        second = decision_body(round_id, alias, 'D', [4, 5], 'redo', 'decide-2')
        decision_receipt = self.desk.ok('POST', '/decision', body=second)
        self.office.ok('POST', '/decision-reconcile',
                       body={'release_id': release_id,
                             'receipt': self.desk.ok('GET', '/decision', query={'request_id': 'decide-2'})})

        # 普通作品 W02 走旧式流程，补齐后才能结册（含第四位复核人 D 的跨组关系）。
        from tests.scenario import comment_input, page_input
        for rel_reviewer in ('A', 'C', 'D'):
            draft = self.desk.ok('POST', '/comment',
                                 body=comment_input(round_id, 'W02', rel_reviewer, f'W02/{rel_reviewer}'))
            page = self.desk.ok('POST', '/page', body=page_input(draft, f'{round_id}/W02/{rel_reviewer}'))
            receipt = self.desk.ok('GET', '/receipt', query={'request_id': f'{round_id}/W02/{rel_reviewer}'})
            self.office.ok('POST', '/reconcile', body=receipt_input(bundle, receipt))
            self.assertEqual(page['page_id'], receipt['page_id'])

        collection = self.office.ok('POST', '/collection', body={'round_id': round_id})
        dual_record = collection['dual_review'][0]
        self.assertEqual(dual_record['alias'], alias)
        # 固定原初评、分歧出处和各子窗实际决定。
        self.assertEqual([p['reviewer_id'] for p in dual_record['prelim_pages']], ['B', 'C'])
        dispute_windows = sorted(d['window'] for d in dual_record['disputes'])
        self.assertEqual(dispute_windows, [[3, 4], [4, 5]])
        for dispute in dual_record['disputes']:
            self.assertEqual(len(dispute['sources']), 2)
            self.assertNotEqual(dispute['sources'][0]['mark'], dispute['sources'][1]['mark'])
        decisions = sorted((d['window'], d['mark']) for d in dual_record['decisions'])
        self.assertEqual(decisions, [([3, 4], 'pass'), ([4, 5], 'redo')])
        # 普通册页保持旧式结构。
        self.assertEqual(sorted((p['alias'], p['reviewer_id']) for p in collection['pages']),
                         [('W02', 'A'), ('W02', 'C'), ('W02', 'D')])
        # 重连不改册。
        self.scene.office.stop()
        self.scene.office.start()
        recovered = self.office.ok('GET', '/collection', query={'round_id': round_id})
        self.assertEqual(recovered, collection)
        self.assertEqual(b_page['page_id'], b_receipt['page_id'])
        self.assertEqual(decision_receipt['request_id'], 'decide-2')

    def test_no_dispute_needs_no_review(self):
        round_id = 'RN'
        _, bundle, alias = self._prepare_dual(round_id)
        release_id = bundle['release_id']
        # 两张页的相反标记只在端点相接 [2,4)/[4,6)，半开区间不相交 => 无分歧。
        b_marks = [{'window': [2, 4], 'mark': 'pass'}]
        c_marks = [{'window': [4, 6], 'mark': 'redo'}]
        for reviewer, marks, req in (('B', b_marks, 'n-B'), ('C', c_marks, 'n-C')):
            self.desk.ok('POST', '/preliminary', body=prelim_body(round_id, alias, reviewer, marks, req))
            receipt = self.desk.ok('GET', '/prelim-receipt', query={'request_id': req})
            self.office.ok('POST', '/prelim-reconcile', body={'release_id': release_id, 'receipt': receipt})
        view = self.desk.ok('GET', '/dispute', query={'round_id': round_id, 'alias': alias})
        self.assertEqual(view['status'], 'cleared')
        self.assertEqual(view['windows'], [])
        # 无分歧时复核无法作答。
        body = decision_body(round_id, alias, 'D', [4, 5], 'pass', 'no-scope')
        self.assertEqual(self.desk.request('POST', '/decision', body=body)[1],
                         {'error': 'outside_dispute_scope'})
        # 普通作品补齐即可结册，双评作品无需任何复核决定。
        from tests.scenario import comment_input, page_input
        for rel_reviewer in ('A', 'C', 'D'):
            draft = self.desk.ok('POST', '/comment',
                                 body=comment_input(round_id, 'W02', rel_reviewer, f'W02/{rel_reviewer}'))
            self.desk.ok('POST', '/page', body=page_input(draft, f'{round_id}/W02/{rel_reviewer}'))
            receipt = self.desk.ok('GET', '/receipt', query={'request_id': f'{round_id}/W02/{rel_reviewer}'})
            self.office.ok('POST', '/reconcile', body=receipt_input(bundle, receipt))
        collection = self.office.ok('POST', '/collection', body={'round_id': round_id})
        self.assertEqual(collection['dual_review'][0]['disputes'], [])
        self.assertEqual(collection['dual_review'][0]['decisions'], [])

    def test_false_attribution_does_not_clear_or_block(self):
        round_id = 'RF'
        _, bundle, alias = self._prepare_dual(round_id)
        release_id = bundle['release_id']
        other_proof = bundle['works'][1]['proof_id']

        # 领评台先出齐两页（office 尚未收任何初评）。
        b_marks = [{'window': [3, 5], 'mark': 'pass'}]
        c_marks = [{'window': [3, 5], 'mark': 'redo'}]
        for reviewer, marks, req in (('B', b_marks, 'f-B'), ('C', c_marks, 'f-C')):
            self.desk.ok('POST', '/preliminary', body=prelim_body(round_id, alias, reviewer, marks, req))

        # 领评台出具的真实复核首执 [3,4)，先只在 office 侧制造两类不符变体，再正常核回。
        good = decision_body(round_id, alias, 'D', [3, 4], 'pass', 'good')
        self.desk.ok('POST', '/decision', body=good)
        genuine = self.desk.ok('GET', '/decision', query={'request_id': 'good'})

        # 伪归属：篡改 proof_id 到另一作品，结构性硬错直接拒绝，不入待核。
        forged = {**genuine, 'request_id': 'forged', 'proof_id': other_proof}
        self.assertEqual(
            self.office.request('POST', '/decision-reconcile',
                                body={'release_id': release_id, 'receipt': forged})[1],
            {'error': 'receipt_excerpt_mismatch'},
        )

        # 范围不符的首执结构合法，先存待核，初评到齐后按实际原页判负。
        parked_bad = {**genuine, 'request_id': 'parked-bad', 'window': [5, 6]}
        self.assertTrue(self.office.ok(
            'POST', '/decision-reconcile',
            body={'release_id': release_id, 'receipt': parked_bad})['held'])

        # 初评到齐：待核越界首执判负，不消失也不挡后续；分歧 [3,5) 全部待裁。
        for req in ('f-B', 'f-C'):
            receipt = self.desk.ok('GET', '/prelim-receipt', query={'request_id': req})
            self.office.ok('POST', '/prelim-reconcile', body={'release_id': release_id, 'receipt': receipt})
        status = self.office.ok('GET', '/reconcile', query={'release_id': release_id})
        self.assertEqual(status['dual_review'][0]['undecided_windows'], [[3, 5]])

        # 真实 good 首执正常核回，裁决 [3,4)；再对 [4,5) 分批作答。
        result = self.office.ok('POST', '/decision-reconcile',
                                body={'release_id': release_id, 'receipt': genuine})
        self.assertEqual(result['dual_review'][0]['undecided_windows'], [[4, 5]])
        second = decision_body(round_id, alias, 'D', [4, 5], 'redo', 'valid-2')
        self.desk.ok('POST', '/decision', body=second)
        receipt = self.desk.ok('GET', '/decision', query={'request_id': 'valid-2'})
        result = self.office.ok('POST', '/decision-reconcile',
                                body={'release_id': release_id, 'receipt': receipt})
        self.assertEqual(result['dual_review'][0]['undecided_windows'], [])

        # 已被裁决的子窗不能重复受理（desk 与 office 双重拦截）。
        duplicate = decision_body(round_id, alias, 'D', [4, 5], 'pass', 'dup')
        self.assertEqual(
            self.desk.request('POST', '/decision', body=duplicate)[1],
            {'error': 'window_already_decided'},
        )
        # office 侧：由真实首执篡改出的重复首执同样被拦。
        dup_receipt = {**receipt, 'request_id': 'dup', 'mark': 'pass'}
        self.assertEqual(
            self.office.request('POST', '/decision-reconcile',
                                body={'release_id': release_id, 'receipt': dup_receipt})[1],
            {'error': 'window_already_decided'},
        )

    def test_ordinary_round_keeps_legacy_collection(self):
        # 旧式结册：完全不携带 dual_review，响应也不出现该字段。
        body = release_input(self.office, self.sample)
        bundle = self.office.ok('POST', '/release', body=body)
        self.assertNotIn('dual_review', bundle)
        self.desk.ok('POST', '/install', body=bundle)
        from tests.scenario import RELATIONS, comment_input, page_input
        for alias, reviewer in RELATIONS:
            draft = self.desk.ok('POST', '/comment',
                                 body=comment_input('R', alias, reviewer, self.sample['comments'][f'{alias}/{reviewer}']))
            self.desk.ok('POST', '/page', body=page_input(draft, f'R/{alias}/{reviewer}'))
            receipt = self.desk.ok('GET', '/receipt', query={'request_id': f'R/{alias}/{reviewer}'})
            self.office.ok('POST', '/reconcile', body=receipt_input(bundle, receipt))
        collection = self.office.ok('POST', '/collection', body={'round_id': 'R'})
        self.assertNotIn('dual_review', collection)
        self.assertEqual(sorted((p['alias'], p['reviewer_id']) for p in collection['pages']),
                         sorted(RELATIONS))

    def test_invalid_designation_rejected(self):
        works = []
        for work in self.sample['works']:
            proof = self.office.ok('POST', '/proof', body=work['proof'])
            works.append({'work_id': work['work_id'], 'group': work['group'], 'proof_id': proof['proof_id']})
        base = {'round_id': 'RX', 'works': works, 'reviewers': self.sample['reviewers']}

        def reject(dual, code):
            self.assertEqual(
                self.office.request('POST', '/release', body={**base, 'dual_review': dual})[1],
                {'error': code},
            )

        # 同组不具回避资格。
        reject([{'work_id': 'P', 'prelim_reviewers': ['A', 'B'], 'adjudicator': 'C'}],
               'dual_reviewer_not_recused')
        # 初评人重复。
        reject([{'work_id': 'P', 'prelim_reviewers': ['B', 'B'], 'adjudicator': 'A'}],
               'invalid_dual_prelim_reviewers')
        # 复核人未登记。
        reject([{'work_id': 'P', 'prelim_reviewers': ['B', 'C'], 'adjudicator': 'Z'}],
               'invalid_dual_reviewer')
        # 作品不存在。
        reject([{'work_id': 'NOPE', 'prelim_reviewers': ['B', 'C'], 'adjudicator': 'A'}],
               'invalid_dual_work')

    def test_mark_window_rules(self):
        round_id = 'RM'
        _, bundle, alias = self._prepare_dual(round_id)
        # 重叠拍窗拒绝。
        overlapping = [{'window': [2, 4], 'mark': 'pass'}, {'window': [3, 5], 'mark': 'redo'}]
        self.assertEqual(
            self.desk.request('POST', '/preliminary',
                              body=prelim_body(round_id, alias, 'B', overlapping, 'm1'))[1],
            {'error': 'overlapping_mark_windows'},
        )
        # 非法标记拒绝。
        bad_mark = [{'window': [2, 4], 'mark': 'maybe'}]
        self.assertEqual(
            self.desk.request('POST', '/preliminary',
                              body=prelim_body(round_id, alias, 'B', bad_mark, 'm2'))[1],
            {'error': 'invalid_mark'},
        )
        # 非锁定初评人不能出页。
        ok_marks = [{'window': [2, 4], 'mark': 'pass'}]
        self.assertEqual(
            self.desk.request('POST', '/preliminary',
                              body=prelim_body(round_id, alias, 'A', ok_marks, 'm3'))[1],
            {'error': 'not_dual_prelim_reviewer'},
        )
        # 越出节选覆盖拒绝，且不占页。
        out_of_cover = [{'window': [6, 7], 'mark': 'pass'}]
        self.assertEqual(
            self.desk.request('POST', '/preliminary',
                              body=prelim_body(round_id, alias, 'B', out_of_cover, 'm4'))[1],
            {'error': 'window_not_covered'},
        )
        valid = prelim_body(round_id, alias, 'B', ok_marks, 'm5')
        page = self.desk.ok('POST', '/preliminary', body=valid)
        # 同号同参复领取原页。
        self.assertEqual(self.desk.ok('POST', '/preliminary', body=valid), page)
        changed = {**valid, 'request_id': 'm5', 'marks': [{'window': [2, 5], 'mark': 'pass'}]}
        self.assertEqual(
            self.desk.request('POST', '/preliminary', body=changed)[1],
            {'error': 'prelim_request_conflict'},
        )

    def test_state_survives_restart_and_collection_is_fixed(self):
        from tests.scenario import comment_input, page_input
        round_id = 'RP'
        _, bundle, alias = self._prepare_dual(round_id)
        release_id = bundle['release_id']
        for reviewer, marks, req in (
            ('B', [{'window': [3, 5], 'mark': 'pass'}], 'p-B'),
            ('C', [{'window': [3, 5], 'mark': 'redo'}], 'p-C'),
        ):
            self.desk.ok('POST', '/preliminary', body=prelim_body(round_id, alias, reviewer, marks, req))
            receipt = self.desk.ok('GET', '/prelim-receipt', query={'request_id': req})
            self.office.ok('POST', '/prelim-reconcile', body={'release_id': release_id, 'receipt': receipt})
        for window, req in (([3, 4], 'p-d1'), ([4, 5], 'p-d2')):
            self.desk.ok('POST', '/decision',
                         body=decision_body(round_id, alias, 'D', window, 'pass', req))
            receipt = self.desk.ok('GET', '/decision', query={'request_id': req})
            self.office.ok('POST', '/decision-reconcile',
                           body={'release_id': release_id, 'receipt': receipt})
        for reviewer in ('A', 'C', 'D'):
            draft = self.desk.ok('POST', '/comment',
                                 body=comment_input(round_id, 'W02', reviewer, f'W02/{reviewer}'))
            self.desk.ok('POST', '/page', body=page_input(draft, f'{round_id}/W02/{reviewer}'))
            receipt = self.desk.ok('GET', '/receipt', query={'request_id': f'{round_id}/W02/{reviewer}'})
            self.office.ok('POST', '/reconcile', body=receipt_input(bundle, receipt))
        collection = self.office.ok('POST', '/collection', body={'round_id': round_id})

        # 场务重连：册固定，欠办为空。
        self.scene.office.stop()
        self.scene.office.start()
        office = self.scene.office.client
        self.assertEqual(office.ok('GET', '/collection', query={'round_id': round_id}), collection)
        status = office.ok('GET', '/reconcile', query={'release_id': release_id})
        self.assertEqual(status['missing'], [])
        self.assertEqual(status['dual_review'][0]['undecided_windows'], [])

        # 领评重连：原初评页与已清状态保留。
        self.scene.desk.stop()
        self.scene.desk.start()
        desk = self.scene.desk.client
        view = desk.ok('GET', '/dispute', query={'round_id': round_id, 'alias': alias})
        self.assertEqual(view['status'], 'cleared')
        page_id = collection['dual_review'][0]['prelim_pages'][0]['page_id']
        self.assertEqual(desk.ok('GET', '/prelim-page', query={'page_id': page_id})['marks'],
                         [{'window': [3, 5], 'mark': 'pass'}])
