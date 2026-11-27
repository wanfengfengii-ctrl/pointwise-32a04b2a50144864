import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from desk.http import make_desk_server
from issue.office_http import make_office_server
from tests.http_fixture import LoopbackService


RELATIONS = (('W01', 'B'), ('W01', 'C'), ('W02', 'A'), ('W02', 'C'))
LAST_RELATION = [{'alias': 'W02', 'reviewer_id': 'C'}]
SAMPLE_PATH = Path(__file__).resolve().parents[1] / 'samples' / 'festival.json'


def load_sample():
    return json.loads(SAMPLE_PATH.read_text(encoding='utf-8'))


def proof_input(sample, work_id):
    return next(work['proof'] for work in sample['works'] if work['work_id'] == work_id)


def release_input(office, sample, round_id=None):
    works = []
    for work in sample['works']:
        proof = office.ok('POST', '/proof', body=work['proof'])
        works.append({'work_id': work['work_id'], 'group': work['group'], 'proof_id': proof['proof_id']})
    return {'round_id': round_id if round_id is not None else sample['round_id'], 'works': works, 'reviewers': sample['reviewers']}


def comment_input(round_id, alias, reviewer_id, text, window=None):
    return {
        'round_id': round_id,
        'alias': alias,
        'reviewer_id': reviewer_id,
        'window': [3, 5] if window is None else window,
        'text': text,
    }


def page_input(draft, request_id):
    return {
        'round_id': draft['round_id'],
        'alias': draft['alias'],
        'reviewer_id': draft['reviewer_id'],
        'draft_id': draft['draft_id'],
        'request_id': request_id,
    }


def receipt_input(bundle, receipt):
    return {'release_id': bundle['release_id'], 'receipt': receipt}


def issue_sample_pages(desk, bundle, sample, relations=RELATIONS):
    pages = []
    for alias, reviewer in relations:
        key = f'{alias}/{reviewer}'
        draft = desk.ok('POST', '/comment', body=comment_input(bundle['round_id'], alias, reviewer, sample['comments'][key]))
        request = page_input(draft, f'{bundle["round_id"]}/{key}')
        page = desk.ok('POST', '/page', body=request)
        receipt = desk.ok('GET', '/receipt', query={'request_id': request['request_id']})
        if receipt['page_id'] != page['page_id'] or receipt['draft_id'] != draft['draft_id'] or receipt['text'] != draft['text']:
            raise AssertionError('receipt does not describe the selected draft and issued page')
        pages.append(receipt)
    return pages


def emit(case_id, input_value, expected, actual, downstream_expected, downstream_actual, code_paths, oracle):
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': case_id,
        'input': input_value,
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': code_paths,
        'oracle': oracle,
    }, ensure_ascii=False, sort_keys=True))


class Scenario:
    def __init__(self, directory):
        self.office = LoopbackService(make_office_server, directory / 'office.sqlite')
        self.desk = LoopbackService(make_desk_server, directory / 'desk.sqlite')

    def __enter__(self):
        try:
            self.office.start()
            self.desk.start()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exception):
        self.desk.stop()
        self.office.stop()

    def prepare(self, sample, round_id=None):
        body = release_input(self.office.client, sample, round_id)
        bundle = self.office.client.ok('POST', '/release', body=body)
        self.desk.client.ok('POST', '/install', body=bundle)
        return body, bundle


class FestivalCase(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.scene = self.enterContext(Scenario(directory))
        self.sample = load_sample()

    @property
    def office(self):
        return self.scene.office.client

    @property
    def desk(self):
        return self.scene.desk.client

    def draft(self, alias, reviewer_id, text='请留意换段时的气口。', *, round_id='R', window=None):
        return self.desk.ok('POST', '/comment', body=comment_input(round_id, alias, reviewer_id, text, window))


def main():
    sample = load_sample()
    with TemporaryDirectory() as directory, Scenario(Path(directory)) as scene:
        proof_body = proof_input(sample, 'P')
        proof = scene.office.client.ok('POST', '/proof', body=proof_body)
        _, bundle = scene.prepare(sample)
        installed = scene.desk.client.ok('GET', '/install', query={'round_id': 'R'})
        actual_spans = [[span['segment_id'], span['window']] for span in proof['spans']]
        installed_spans = [[span['segment_id'], span['window']] for span in installed['bundle']['works'][0]['spans']]
        expected_spans = [['S1', [2, 4]], ['S2', [4, 6]]]
        assert actual_spans == expected_spans and installed_spans == expected_spans
        assert [(item['alias'], item['reviewer_id']) for item in bundle['eligible']] == list(RELATIONS)
        emit('n1', proof_body, expected_spans, actual_spans, expected_spans, installed_spans,
             ['scores/excerpts.py', 'scores/proofs.py', 'issue/release.py', 'desk/install.py'],
             '手算 [2,6) 和两段的正长交集，并在已装件核对同一节选。')

        scene.office.stop()
        receipts = issue_sample_pages(scene.desk.client, bundle, sample)
        expected_pages = [(alias, reviewer, sample['comments'][f'{alias}/{reviewer}']) for alias, reviewer in RELATIONS]
        actual_pages = [(page['alias'], page['reviewer_id'], page['text']) for page in receipts]
        assert actual_pages == expected_pages
        stored = scene.desk.client.ok('GET', '/receipts', query={'round_id': 'R'})['receipts']
        assert stored == receipts
        emit('n4', {'round_id': 'R', 'window': [3, 5], 'office_running': False},
             expected_pages, actual_pages, [page['page_id'] for page in receipts], [page['page_id'] for page in stored],
             ['desk/comments.py', 'desk/pages.py', 'desk/receipts.py'], '按固定跨组名单手列四条关系，并逐页核对原文字和已提交首执。')

        scene.office.start()
        for receipt in receipts[:-1]:
            missing = scene.office.client.ok('POST', '/reconcile', body=receipt_input(bundle, receipt))['missing']
        status, blocked = scene.office.client.request('POST', '/collection', body={'round_id': 'R'})
        assert missing == LAST_RELATION and status == 409 and blocked['missing'] == LAST_RELATION
        emit('n7', {'received': [page['page_id'] for page in receipts[:-1]]},
             LAST_RELATION, missing, {'status': 409, 'missing': LAST_RELATION},
             {'status': status, 'missing': blocked['missing']}, ['archive/reconcile.py', 'archive/close.py'],
             '四条手算应办关系减去前三笔首执后只余 W02/C。')
        completed = scene.office.client.ok('POST', '/reconcile', body=receipt_input(bundle, receipts[-1]))
        assert completed['missing'] == []
        collection = scene.office.client.ok('POST', '/collection', body={'round_id': 'R'})
        assert collection['pages'] == receipts
        scene.office.stop()
        scene.office.start()
        recovered = scene.office.client.ok('GET', '/collection', query={'round_id': 'R'})
        assert recovered == collection
        emit('n8', {'round_id': 'R', 'returned_receipts': len(receipts)},
             [page['page_id'] for page in receipts], [page['page_id'] for page in collection['pages']],
             collection, recovered, ['archive/close.py', 'archive/readback.py'],
             '按实际出页首执逐个核对册页号，再与重开后的返回逐字段比较。')


if __name__ == '__main__':
    main()
