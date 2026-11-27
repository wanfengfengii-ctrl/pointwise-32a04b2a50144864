from copy import deepcopy

from tests.scenario import FestivalCase, LAST_RELATION, RELATIONS, emit, issue_sample_pages, receipt_input


class TestClose(FestivalCase):
    def test_missing_receipt(self):
        _, bundle = self.scene.prepare(self.sample)
        receipts = issue_sample_pages(self.desk, bundle, self.sample)
        for receipt in receipts[:3]:
            self.office.ok('POST', '/reconcile', body=receipt_input(bundle, receipt))
        query = {'release_id': bundle['release_id']}
        missing = self.office.ok('GET', '/reconcile', query=query)['missing']
        self.assertEqual(missing, LAST_RELATION)
        repeated = self.office.ok('POST', '/reconcile', body=receipt_input(bundle, receipts[0]))
        self.assertEqual(repeated['missing'], LAST_RELATION)
        round_query = {'round_id': 'R'}
        self.assertEqual(self.office.request('GET', '/collection', query=round_query)[0], 404)
        status, blocked = self.office.request('POST', '/collection', body=round_query)
        self.assertEqual((status, blocked), (409, {'error': 'collection_missing_pages', 'missing': LAST_RELATION}))
        self.assertEqual(self.office.request('GET', '/collection', query=round_query)[0], 404)
        self.assertEqual(self.office.ok('POST', '/reconcile', body=receipt_input(bundle, receipts[3]))['missing'], [])
        collection = self.office.ok('POST', '/collection', body=round_query)
        self.assertEqual(collection['pages'], receipts)
        emit('n7.exact_missing', {'round_id': 'R', 'returned': [page['page_id'] for page in receipts[:3]]},
             LAST_RELATION, missing, 409, status, ['archive/reconcile.py', 'archive/close.py'],
             '固定四条应办关系中只有 W02/C 的首执未交回，结册须被阻止。')

    def test_mismatched_receipt(self):
        _, first = self.scene.prepare(self.sample, 'R1')
        _, second = self.scene.prepare(self.sample, 'R2')
        first_receipt = issue_sample_pages(self.desk, first, self.sample, [('W01', 'B')])[0]
        second_receipt = issue_sample_pages(self.desk, second, self.sample, [('W01', 'B')])[0]
        query = {'release_id': first['release_id']}
        expected_missing = [{'alias': alias, 'reviewer_id': reviewer} for alias, reviewer in RELATIONS]
        self.assertEqual(self.office.ok('GET', '/reconcile', query=query)['missing'], expected_missing)
        foreign = self.office.request('POST', '/reconcile', body=receipt_input(first, second_receipt))
        self.assertEqual(foreign, (409, {'error': 'receipt_release_mismatch'}))
        for altered, code in (
            ({**first_receipt, 'round_id': 'R2'}, 'receipt_round_mismatch'),
            ({**first_receipt, 'reviewer_id': 'A'}, 'receipt_relation_mismatch'),
            ({**first_receipt, 'proof_id': first['works'][1]['proof_id']}, 'receipt_excerpt_mismatch'),
            ({**first_receipt, 'window': [3, 7]}, 'receipt_excerpt_mismatch'),
            ({**first_receipt, 'text': '内容与原页号不一致'}, 'receipt_page_mismatch'),
        ):
            with self.subTest(error=code):
                self.assertEqual(self.office.request('POST', '/reconcile', body=receipt_input(first, altered)),
                                 (409, {'error': code}))
        self.assertEqual(self.office.ok('GET', '/reconcile', query=query)['missing'], expected_missing)
        self.assertEqual(self.office.ok('POST', '/reconcile', body=receipt_input(first, first_receipt))['missing'], expected_missing[1:])

    def test_empty_eligibility(self):
        sample = deepcopy(self.sample)
        for entry in sample['works'] + sample['reviewers']:
            entry['group'] = '甲'
        _, bundle = self.scene.prepare(sample)
        self.assertEqual(bundle['eligible'], [])
        self.assertEqual(self.office.ok('GET', '/reconcile', query={'release_id': bundle['release_id']})['missing'], [])
        collection = self.office.ok('POST', '/collection', body={'round_id': 'R'})
        self.assertEqual(collection['pages'], [])
        self.assertEqual(self.office.ok('GET', '/collection', query={'round_id': 'R'}), collection)

    def test_frozen_collection(self):
        _, bundle = self.scene.prepare(self.sample)
        receipts = issue_sample_pages(self.desk, bundle, self.sample)
        for index in (3, 1, 0, 2):
            self.office.ok('POST', '/reconcile', body=receipt_input(bundle, receipts[index]))
        round_query = {'round_id': 'R'}
        collection = self.office.ok('POST', '/collection', body=round_query)
        expected_ids = [receipt['page_id'] for receipt in receipts]
        actual_ids = [page['page_id'] for page in collection['pages']]
        self.assertEqual(actual_ids, expected_ids)
        self.assertEqual(len(set(actual_ids)), 4)
        self.assertEqual([(page['alias'], page['reviewer_id']) for page in collection['pages']], list(RELATIONS))
        self.assertEqual(collection['pages'], receipts)
        self.assertEqual(self.office.ok('POST', '/reconcile', body=receipt_input(bundle, receipts[1]))['missing'], [])
        conflicting = {**receipts[1], 'request_id': 'contradictory-request'}
        self.assertEqual(self.office.request('POST', '/reconcile', body=receipt_input(bundle, conflicting)),
                         (409, {'error': 'verified_receipt_conflict'}))
        self.assertEqual(self.office.ok('POST', '/collection', body=round_query), collection)
        self.scene.office.stop()
        self.scene.office.start()
        recovered = self.office.ok('GET', '/collection', query=round_query)
        self.assertEqual(recovered, collection)
        emit('n8.each_actual_page', {'intake_order': [3, 1, 0, 2]}, expected_ids, actual_ids,
             collection, recovered, ['archive/intake.py', 'archive/close.py', 'archive/readback.py'],
             '四个出页时取得的页号按手列的匿名关系排列，逐个核对并确认 C 的两页都在原册。')
