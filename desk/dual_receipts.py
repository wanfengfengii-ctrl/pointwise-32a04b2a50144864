from dataclasses import dataclass
import json

from dual.marks import MARKS, MarkedWindow
from festival import BusinessError, object_fields, required_text
from scores.windows import BeatWindow, parse_beat_window


@dataclass(frozen=True)
class PrelimReceipt:
    request_id: str
    page_id: str
    release_id: str
    round_id: str
    alias: str
    reviewer_id: str
    proof_id: str
    marks: tuple[MarkedWindow, ...]

    def original_parameters(self):
        return self.round_id, self.alias, self.reviewer_id, self.marks

    def as_json(self):
        return {
            'request_id': self.request_id,
            'page_id': self.page_id,
            'release_id': self.release_id,
            'round_id': self.round_id,
            'alias': self.alias,
            'reviewer_id': self.reviewer_id,
            'proof_id': self.proof_id,
            'marks': [entry.as_json() for entry in self.marks],
        }


def init_dual_receipts(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS prelim_receipts (
            request_id TEXT PRIMARY KEY,
            page_id TEXT NOT NULL UNIQUE REFERENCES formal_prelim_pages(page_id)
        )
    ''')


def write_prelim_receipt(connection, request_id, page):
    connection.execute('INSERT INTO prelim_receipts VALUES (?, ?)', (request_id, page.page_id))


def read_prelim_receipt_by_request(connection, request_id):
    row = connection.execute('''
        SELECT r.request_id, p.page_id, p.content
        FROM prelim_receipts AS r JOIN formal_prelim_pages AS p ON p.page_id = r.page_id
        WHERE r.request_id = ?
    ''', (request_id,)).fetchone()
    if row is None:
        return None
    return decode_prelim_receipt(
        {'request_id': row['request_id'], 'page_id': row['page_id'], **json.loads(row['content'])}
    )


def encode_prelim_receipt(receipt):
    return receipt.as_json()


def decode_prelim_receipt(value):
    text_fields = ('request_id', 'page_id', 'release_id', 'round_id', 'alias', 'reviewer_id', 'proof_id')
    object_fields(value, *text_fields, 'marks')
    fields = {field: required_text(value[field], field) for field in text_fields}
    marks = []
    for item in value['marks']:
        object_fields(item, 'window', 'mark')
        marks.append(MarkedWindow(parse_beat_window(item['window']), item['mark'] if item['mark'] in MARKS else _invalid()))
    return PrelimReceipt(marks=tuple(marks), **fields)


def _invalid():
    raise BusinessError(422, 'invalid_mark')


@dataclass(frozen=True)
class DecisionReceipt:
    request_id: str
    decision_id: str
    release_id: str
    round_id: str
    alias: str
    adjudicator: str
    proof_id: str
    window: BeatWindow
    mark: str

    def original_parameters(self):
        return self.round_id, self.alias, self.adjudicator, self.window, self.mark

    def as_json(self):
        return {
            'request_id': self.request_id,
            'decision_id': self.decision_id,
            'release_id': self.release_id,
            'round_id': self.round_id,
            'alias': self.alias,
            'adjudicator': self.adjudicator,
            'proof_id': self.proof_id,
            'window': self.window.as_json(),
            'mark': self.mark,
        }


def init_decision_receipts(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS decision_receipts (
            decision_id TEXT PRIMARY KEY,
            release_id TEXT NOT NULL,
            round_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            adjudicator TEXT NOT NULL,
            proof_id TEXT NOT NULL,
            window TEXT NOT NULL,
            mark TEXT NOT NULL
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS decision_requests (
            request_id TEXT PRIMARY KEY,
            decision_id TEXT NOT NULL UNIQUE REFERENCES decision_receipts(decision_id)
        )
    ''')


def read_decision_by_request(connection, request_id):
    row = connection.execute('''
        SELECT r.request_id, d.*
        FROM decision_requests AS r
        JOIN decision_receipts AS d ON d.decision_id = r.decision_id
        WHERE r.request_id = ?
    ''', (request_id,)).fetchone()
    if row is None:
        return None
    return _decision_from_row(row['request_id'], row)


def _decision_from_row(request_id, row):
    return DecisionReceipt(
        request_id, row['decision_id'], row['release_id'], row['round_id'], row['alias'],
        row['adjudicator'], row['proof_id'], parse_beat_window(json.loads(row['window'])), row['mark'],
    )


def encode_decision_receipt(receipt):
    return receipt.as_json()


def decode_decision_receipt(value):
    text_fields = ('request_id', 'decision_id', 'release_id', 'round_id', 'alias', 'adjudicator', 'proof_id')
    object_fields(value, *text_fields, 'window', 'mark')
    fields = {field: required_text(value[field], field) for field in text_fields}
    if value['mark'] not in MARKS:
        raise BusinessError(422, 'invalid_mark')
    return DecisionReceipt(**fields, window=parse_beat_window(value['window']), mark=value['mark'])
