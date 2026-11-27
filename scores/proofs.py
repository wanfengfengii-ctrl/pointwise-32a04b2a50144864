from dataclasses import dataclass
import json

from festival import BusinessError, atomic, canonical_json, object_fields, required_text, serial_id, serial_number
from scores.excerpts import ExcerptSpan, build_excerpt
from scores.revisions import Revision, store_revision
from scores.segments import parse_segments
from scores.windows import BeatWindow, parse_beat_window


@dataclass(frozen=True)
class FrozenProof:
    proof_id: str
    revision_id: str
    window: BeatWindow
    spans: tuple[ExcerptSpan, ...]

    def as_json(self):
        return {
            'proof_id': self.proof_id,
            'revision_id': self.revision_id,
            'window': self.window.as_json(),
            'spans': [span.with_source() for span in self.spans],
        }


def init_proofs(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS score_proofs (
            serial INTEGER PRIMARY KEY,
            revision_id TEXT NOT NULL REFERENCES score_revisions(revision_id),
            window TEXT NOT NULL,
            spans TEXT NOT NULL,
            UNIQUE (revision_id, window)
        )
    ''')


def freeze_proof(connection, body):
    object_fields(body, 'revision_id', 'author', 'segments', 'window')
    revision = Revision(
        required_text(body['revision_id'], 'revision_id'),
        required_text(body['author'], 'author'),
        parse_segments(body['segments']),
    )
    window = parse_beat_window(body['window'])
    stored_window = canonical_json(window.as_json())
    with atomic(connection):
        store_revision(connection, revision)
        previous = connection.execute(
            'SELECT * FROM score_proofs WHERE revision_id = ? AND window = ?',
            (revision.revision_id, stored_window),
        ).fetchone()
        if previous is not None:
            return _proof_from_row(previous)
        spans = build_excerpt(revision.revision_id, revision.segments, window)
        stored_spans = canonical_json([span.anonymous() for span in spans])
        cursor = connection.execute(
            'INSERT INTO score_proofs (revision_id, window, spans) VALUES (?, ?, ?)',
            (revision.revision_id, stored_window, stored_spans),
        )
        return FrozenProof(serial_id('proof', cursor.lastrowid), revision.revision_id, window, spans)


def read_proof(connection, proof_id):
    row = connection.execute(
        'SELECT * FROM score_proofs WHERE serial = ?', (serial_number('proof', proof_id),)
    ).fetchone()
    if row is None:
        raise BusinessError(404, 'proof_not_found')
    return _proof_from_row(row)


def _proof_from_row(row):
    revision_id = row['revision_id']
    spans = tuple(
        ExcerptSpan(revision_id, span['segment_id'], parse_beat_window(span['window']), span['text'])
        for span in json.loads(row['spans'])
    )
    return FrozenProof(
        serial_id('proof', row['serial']), revision_id, parse_beat_window(json.loads(row['window'])), spans
    )
