from copy import deepcopy

from tests.scenario import FestivalCase, RELATIONS, emit, proof_input, release_input


class TestPrepare(FestivalCase):
    def test_excerpt(self):
        body = proof_input(self.sample, 'P')
        proof = self.office.ok('POST', '/proof', body=body)
        expected = [
            {'segment_id': 'S1', 'window': [2, 4], 'text': '溪水绕过石桥', 'revision_id': 'score-P-1'},
            {'segment_id': 'S2', 'window': [4, 6], 'text': '和声停在晚风', 'revision_id': 'score-P-1'},
        ]
        self.assertEqual(proof['spans'], expected)
        self.assertEqual(proof['window'], [2, 6])
        self.assertEqual(self.office.ok('GET', '/proof', query={'proof_id': proof['proof_id']}), proof)
        _, bundle = self.scene.prepare(self.sample)
        issued = bundle['works'][0]
        expected_public = [
            {'segment_id': 'S1', 'window': [2, 4], 'text': '溪水绕过石桥'},
            {'segment_id': 'S2', 'window': [4, 6], 'text': '和声停在晚风'},
        ]
        self.assertEqual(issued, {'alias': 'W01', 'proof_id': proof['proof_id'], 'spans': expected_public})
        emit('n1.intersection_provenance', body, expected, proof['spans'], expected_public, issued['spans'],
             ['scores/windows.py', 'scores/excerpts.py', 'scores/proofs.py', 'issue/release.py'],
             '两段分别取与 [2,6) 的较晚起拍和较早止拍，原文字保持段级。')

    def test_registered_order_breaks_start_ties(self):
        body = {
            'revision_id': 'tie', 'author': '合唱队', 'window': [2, 6],
            'segments': [
                {'segment_id': 'S3', 'window': [5, 9], 'text': '末段'},
                {'segment_id': 'S2', 'window': [0, 4], 'text': '登记在前'},
                {'segment_id': 'S1', 'window': [0, 7], 'text': '登记在后'},
            ],
        }
        proof = self.office.ok('POST', '/proof', body=body)
        self.assertEqual([(span['segment_id'], span['window']) for span in proof['spans']],
                         [('S2', [2, 4]), ('S1', [2, 6]), ('S3', [5, 6])])

    def test_empty(self):
        original = proof_input(self.sample, 'P')
        status, error = self.office.request('POST', '/proof', body={**original, 'window': [8, 9]})
        self.assertEqual((status, error), (422, {'error': 'empty_excerpt'}))
        self.assertEqual(self.office.request('GET', '/proof', query={'proof_id': 'proof-1'})[0], 404)
        valid = self.office.ok('POST', '/proof', body=original)
        self.assertEqual(valid['proof_id'], 'proof-1')
        self.assertEqual([span['window'] for span in valid['spans']], [[2, 4], [4, 6]])

    def test_invalid_window(self):
        original = proof_input(self.sample, 'P')
        for window in ([True, 6], [2, False], ['2', 6], [2.0, 6], [2], [2, None], [6, 6], [7, 6], None):
            with self.subTest(window=window):
                status, error = self.office.request('POST', '/proof', body={**original, 'window': window})
                self.assertEqual((status, error), (422, {'error': 'invalid_beat_window'}))
        missing_window = {key: value for key, value in original.items() if key != 'window'}
        self.assertEqual(self.office.request('POST', '/proof', body=missing_window)[0], 422)
        bad_segment = deepcopy(original)
        bad_segment['segments'][0]['window'] = [False, 4]
        self.assertEqual(self.office.request('POST', '/proof', body=bad_segment)[0], 422)
        self.assertEqual(self.office.request('GET', '/proof', query={'proof_id': 'proof-1'})[0], 404)

    def test_frozen_roster(self):
        body, bundle = self.scene.prepare(self.sample)
        changed = deepcopy(body)
        next(item for item in changed['reviewers'] if item['reviewer_id'] == 'B')['group'] = '甲'
        self.assertEqual(self.office.request('POST', '/release', body=changed), (409, {'error': 'roster_conflict'}))
        self.assertEqual(self.office.ok('GET', '/release', query={'round_id': 'R'}), bundle)
        self.assertEqual(self.office.ok('GET', '/release', query={'release_id': bundle['release_id']}), bundle)
        self.assertEqual([(item['alias'], item['reviewer_id']) for item in bundle['eligible']], list(RELATIONS))
        reordered = {**body, 'works': body['works'][::-1], 'reviewers': body['reviewers'][::-1]}
        self.assertEqual(self.office.ok('POST', '/release', body=reordered), bundle)
        self.assertEqual(self.desk.ok('POST', '/install', body=bundle)['bundle'], bundle)
        self.assertEqual(bundle['reviewers'], ['A', 'B', 'C'])
        self.assertEqual([item['alias'] for item in bundle['works']], ['W01', 'W02'])
        for item in bundle['works']:
            self.assertEqual(set(item), {'alias', 'proof_id', 'spans'})
            for span in item['spans']:
                self.assertEqual(set(span), {'segment_id', 'window', 'text'})

    def test_frozen_excerpt_and_office_restart(self):
        body, bundle = self.scene.prepare(self.sample)
        original = bundle['works'][0]
        new_revision = deepcopy(proof_input(self.sample, 'P'))
        new_revision['revision_id'] = 'score-P-2'
        new_revision['window'] = [4, 8]
        new_revision['segments'][1]['text'] = '后建校样采用的新排练词'
        later = self.office.ok('POST', '/proof', body=new_revision)
        self.assertNotEqual(later['proof_id'], original['proof_id'])
        self.assertEqual(later['spans'][0]['window'], [4, 8])
        self.scene.office.stop()
        self.scene.office.start()
        self.assertEqual(self.office.ok('GET', '/proof', query={'proof_id': later['proof_id']}), later)
        self.assertEqual(self.office.ok('POST', '/proof', body=new_revision), later)
        changed_revision = {**new_revision, 'author': '另一支队'}
        self.assertEqual(self.office.request('POST', '/proof', body=changed_revision)[0], 409)
        self.assertEqual(self.office.ok('GET', '/release', query={'round_id': 'R'})['works'][0], original)
        self.assertEqual(self.office.ok('POST', '/release', body=body), bundle)

    def test_unknown_proof_leaves_round_unissued(self):
        body = release_input(self.office, self.sample)
        rejected = deepcopy(body)
        rejected['works'][0]['proof_id'] = 'proof-999'
        self.assertEqual(self.office.request('POST', '/release', body=rejected), (404, {'error': 'proof_not_found'}))
        self.assertEqual(self.office.request('GET', '/release', query={'round_id': 'R'})[0], 404)
        release = self.office.ok('POST', '/release', body=body)
        self.assertEqual(release['round_id'], 'R')
        self.assertEqual(len(release['works']), 2)
