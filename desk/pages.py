from dataclasses import dataclass
import json

from desk.comments import read_comment
from desk.install import read_installed_bundle
from desk.receipts import formal_page_id, read_receipt_by_request, write_receipt
from festival import BusinessError, atomic, canonical_json, object_fields, required_text


@dataclass(frozen=True)
class ReviewPage:
    page_id: str
    content: dict

    def summary(self):
        return {'page_id': self.page_id, 'draft_id': self.content['draft_id']}

    def as_json(self):
        return {'page_id': self.page_id, **self.content}


def init_pages(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS formal_pages (
            page_id TEXT PRIMARY KEY,
            release_id TEXT NOT NULL REFERENCES desk_installs(release_id),
            alias TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,
            content TEXT NOT NULL,
            UNIQUE (release_id, alias, reviewer_id)
        )
    ''')


def issue_page(connection, body):
    fields = ('round_id', 'alias', 'reviewer_id', 'draft_id', 'request_id')
    object_fields(body, *fields)
    round_id, alias, reviewer_id, draft_id, request_id = (required_text(body[key], key) for key in fields)
    with atomic(connection):
        receipt = read_receipt_by_request(connection, request_id)
        if receipt is not None:
            if receipt.original_parameters() != (round_id, alias, reviewer_id, draft_id):
                raise BusinessError(409, 'page_request_conflict')
            return read_page(connection, receipt.page_id)

        payload = read_installed_bundle(connection, round_id).payload
        if (alias, reviewer_id) not in payload.eligible:
            raise BusinessError(409, 'not_eligible')
        draft = read_comment(connection, draft_id)
        draft_key = (payload.release_id, round_id, alias, reviewer_id)
        if draft is None or (draft.release_id, draft.round_id, draft.alias, draft.reviewer_id) != draft_key:
            raise BusinessError(409, 'draft_mismatch')
        existing = connection.execute('''
            SELECT page_id FROM formal_pages WHERE release_id = ? AND alias = ? AND reviewer_id = ?
        ''', (payload.release_id, alias, reviewer_id)).fetchone()
        if existing is not None:
            raise BusinessError(409, 'relation_already_issued')

        content = draft.as_json()
        page_id = formal_page_id(content)
        connection.execute(
            'INSERT INTO formal_pages VALUES (?, ?, ?, ?, ?)',
            (page_id, payload.release_id, alias, reviewer_id, canonical_json(content)),
        )
        write_receipt(connection, request_id, page_id)
        return ReviewPage(page_id, content)


def read_page(connection, page_id):
    row = connection.execute('SELECT content FROM formal_pages WHERE page_id = ?', (page_id,)).fetchone()
    if row is None:
        raise BusinessError(404, 'page_not_found')
    return ReviewPage(page_id, json.loads(row['content']))
