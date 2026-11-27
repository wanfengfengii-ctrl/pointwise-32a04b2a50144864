from dataclasses import dataclass
from hashlib import sha256
import json

from desk.install import read_installed_bundle
from dual.marks import MarkedWindow, parse_marked_windows
from festival import BusinessError, atomic, canonical_json, object_fields, required_text
from scores.windows import BeatWindow


@dataclass(frozen=True)
class PrelimPage:
    page_id: str
    release_id: str
    round_id: str
    alias: str
    reviewer_id: str
    proof_id: str
    marks: tuple[MarkedWindow, ...]

    def content(self):
        return {
            'release_id': self.release_id,
            'round_id': self.round_id,
            'alias': self.alias,
            'reviewer_id': self.reviewer_id,
            'proof_id': self.proof_id,
            'marks': [entry.as_json() for entry in self.marks],
        }

    def summary(self):
        return {'page_id': self.page_id, 'alias': self.alias, 'reviewer_id': self.reviewer_id}


def prelim_page_id(content):
    return 'prelim-' + sha256(canonical_json(content).encode('utf-8')).hexdigest()


def init_prelim_pages(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS formal_prelim_pages (
            page_id TEXT PRIMARY KEY,
            release_id TEXT NOT NULL REFERENCES desk_installs(release_id),
            alias TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,
            content TEXT NOT NULL,
            UNIQUE (release_id, alias, reviewer_id)
        )
    ''')


def issue_prelim_page(connection, body, write_receipt, read_receipt):
    fields = ('round_id', 'alias', 'reviewer_id', 'marks', 'request_id')
    object_fields(body, *fields)
    round_id = required_text(body['round_id'], 'round_id')
    alias = required_text(body['alias'], 'alias')
    reviewer_id = required_text(body['reviewer_id'], 'reviewer_id')
    request_id = required_text(body['request_id'], 'request_id')
    marks = parse_marked_windows(body['marks'])
    with atomic(connection):
        receipt = read_receipt(connection, request_id)
        if receipt is not None:
            if receipt.original_parameters() != (round_id, alias, reviewer_id, marks):
                raise BusinessError(409, 'prelim_request_conflict')
            return read_prelim_page(connection, receipt.page_id)

        payload = read_installed_bundle(connection, round_id).payload
        designation = payload.dual_for_alias(alias)
        if designation is None or reviewer_id not in designation['prelim_reviewers']:
            raise BusinessError(409, 'not_dual_prelim_reviewer')
        excerpt = payload.excerpt_for(alias)
        for entry in marks:
            if not excerpt.covers_window(entry.window):
                raise BusinessError(422, 'window_not_covered')
        existing = connection.execute(
            'SELECT page_id FROM formal_prelim_pages WHERE release_id = ? AND alias = ? AND reviewer_id = ?',
            (payload.release_id, alias, reviewer_id),
        ).fetchone()
        if existing is not None:
            raise BusinessError(409, 'relation_already_issued')

        page = PrelimPage(
            prelim_page_id(_content_payload(payload, round_id, alias, reviewer_id, excerpt, marks)),
            payload.release_id, round_id, alias, reviewer_id, excerpt.proof_id, marks,
        )
        connection.execute(
            'INSERT INTO formal_prelim_pages VALUES (?, ?, ?, ?, ?)',
            (page.page_id, payload.release_id, alias, reviewer_id, canonical_json(page.content())),
        )
        write_receipt(connection, request_id, page)
        return page


def _content_payload(payload, round_id, alias, reviewer_id, excerpt, marks):
    return {
        'release_id': payload.release_id,
        'round_id': round_id,
        'alias': alias,
        'reviewer_id': reviewer_id,
        'proof_id': excerpt.proof_id,
        'marks': [entry.as_json() for entry in marks],
    }


def read_prelim_page(connection, page_id):
    row = connection.execute(
        'SELECT content FROM formal_prelim_pages WHERE page_id = ?', (page_id,)
    ).fetchone()
    if row is None:
        raise BusinessError(404, 'prelim_page_not_found')
    return _page_from_content(json.loads(row['content']))


def _page_from_content(content):
    return PrelimPage(
        prelim_page_id(content),
        content['release_id'], content['round_id'], content['alias'], content['reviewer_id'],
        content['proof_id'],
        tuple(MarkedWindow(BeatWindow(item['window'][0], item['window'][1]), item['mark']) for item in content['marks']),
    )


def read_prelim_pages_for_alias(connection, release_id, alias):
    rows = connection.execute(
        'SELECT content FROM formal_prelim_pages WHERE release_id = ? AND alias = ? ORDER BY reviewer_id',
        (release_id, alias),
    )
    return tuple(_page_from_content(json.loads(row['content'])) for row in rows)
