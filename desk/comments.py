from dataclasses import dataclass
import json

from desk.install import read_installed_bundle
from festival import BusinessError, atomic, canonical_json, object_fields, required_text, serial_id, serial_number
from scores.windows import BeatWindow, parse_beat_window


@dataclass(frozen=True)
class CommentDraft:
    draft_id: str
    release_id: str
    round_id: str
    alias: str
    reviewer_id: str
    proof_id: str
    window: BeatWindow
    text: str

    def as_json(self):
        return {
            'draft_id': self.draft_id,
            'release_id': self.release_id,
            'round_id': self.round_id,
            'alias': self.alias,
            'reviewer_id': self.reviewer_id,
            'proof_id': self.proof_id,
            'window': self.window.as_json(),
            'text': self.text,
        }


def init_comments(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS comment_drafts (
            serial INTEGER PRIMARY KEY,
            release_id TEXT NOT NULL REFERENCES desk_installs(release_id),
            round_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,
            proof_id TEXT NOT NULL,
            window TEXT NOT NULL,
            text TEXT NOT NULL
        )
    ''')


def submit_comment(connection, body):
    object_fields(body, 'round_id', 'alias', 'reviewer_id', 'window', 'text')
    round_id = required_text(body['round_id'], 'round_id')
    alias = required_text(body['alias'], 'alias')
    reviewer_id = required_text(body['reviewer_id'], 'reviewer_id')
    text = required_text(body['text'], 'text')
    window = parse_beat_window(body['window'])
    with atomic(connection):
        payload = read_installed_bundle(connection, round_id).payload
        excerpt = payload.excerpt_for(alias)
        if reviewer_id not in payload.reviewers:
            raise BusinessError(404, 'reviewer_not_found')
        if not excerpt.covers_window(window):
            raise BusinessError(422, 'window_not_covered')
        cursor = connection.execute('''
            INSERT INTO comment_drafts (release_id, round_id, alias, reviewer_id, proof_id, window, text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (payload.release_id, round_id, alias, reviewer_id, excerpt.proof_id, canonical_json(window.as_json()), text))
        return CommentDraft(
            serial_id('draft', cursor.lastrowid), payload.release_id, round_id,
            alias, reviewer_id, excerpt.proof_id, window, text,
        )


def read_comment(connection, draft_id):
    row = connection.execute(
        'SELECT * FROM comment_drafts WHERE serial = ?', (serial_number('draft', draft_id),)
    ).fetchone()
    if row is None:
        return None
    return CommentDraft(
        draft_id, row['release_id'], row['round_id'], row['alias'], row['reviewer_id'],
        row['proof_id'], parse_beat_window(json.loads(row['window'])), row['text'],
    )
