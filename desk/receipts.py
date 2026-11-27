from dataclasses import dataclass
from hashlib import sha256
import json

from festival import canonical_json, object_fields, required_text
from scores.windows import BeatWindow, parse_beat_window


@dataclass(frozen=True)
class PageReceipt:
    request_id: str
    page_id: str
    release_id: str
    round_id: str
    alias: str
    reviewer_id: str
    draft_id: str
    proof_id: str
    window: BeatWindow
    text: str

    def original_parameters(self):
        return self.round_id, self.alias, self.reviewer_id, self.draft_id

    def page_content(self):
        return {
            'release_id': self.release_id,
            'round_id': self.round_id,
            'alias': self.alias,
            'reviewer_id': self.reviewer_id,
            'draft_id': self.draft_id,
            'proof_id': self.proof_id,
            'window': self.window.as_json(),
            'text': self.text,
        }


def formal_page_id(content):
    digest = sha256(canonical_json(content).encode('utf-8')).hexdigest()
    return f'page-{digest}'


def init_receipts(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS page_receipts (
            request_id TEXT PRIMARY KEY,
            page_id TEXT NOT NULL UNIQUE REFERENCES formal_pages(page_id)
        )
    ''')


def write_receipt(connection, request_id, page_id):
    connection.execute('INSERT INTO page_receipts VALUES (?, ?)', (request_id, page_id))


def read_receipt_by_request(connection, request_id):
    row = connection.execute('''
        SELECT r.request_id, p.page_id, p.content
        FROM page_receipts AS r JOIN formal_pages AS p ON p.page_id = r.page_id
        WHERE r.request_id = ?
    ''', (request_id,)).fetchone()
    if row is None:
        return None
    return _receipt_from_row(row)


def read_receipts_by_release(connection, release_id):
    rows = connection.execute('''
        SELECT r.request_id, p.page_id, p.content
        FROM page_receipts AS r JOIN formal_pages AS p ON p.page_id = r.page_id
        WHERE p.release_id = ? ORDER BY p.alias, p.reviewer_id
    ''', (release_id,))
    return tuple(_receipt_from_row(row) for row in rows)


def encode_receipt(receipt):
    return {'request_id': receipt.request_id, 'page_id': receipt.page_id, **receipt.page_content()}


def decode_receipt(value):
    text_fields = ('request_id', 'page_id', 'release_id', 'round_id', 'alias', 'reviewer_id', 'draft_id', 'proof_id', 'text')
    object_fields(value, *text_fields, 'window')
    fields = {field: required_text(value[field], field) for field in text_fields}
    return PageReceipt(**fields, window=parse_beat_window(value['window']))


def _receipt_from_row(row):
    return decode_receipt({'request_id': row['request_id'], 'page_id': row['page_id'], **json.loads(row['content'])})
