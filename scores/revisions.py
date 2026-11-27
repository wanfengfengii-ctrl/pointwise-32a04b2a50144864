from dataclasses import dataclass
import json

from festival import BusinessError, canonical_json
from scores.segments import Segment, parse_segments


@dataclass(frozen=True)
class Revision:
    revision_id: str
    author: str
    segments: tuple[Segment, ...]


def init_revisions(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS score_revisions (
            revision_id TEXT PRIMARY KEY,
            author TEXT NOT NULL,
            segments TEXT NOT NULL
        )
    ''')


def store_revision(connection, revision):
    previous = read_revision(connection, revision.revision_id)
    if previous is not None:
        if previous != revision:
            raise BusinessError(409, 'revision_conflict')
        return previous
    connection.execute(
        'INSERT INTO score_revisions VALUES (?, ?, ?)',
        (revision.revision_id, revision.author, canonical_json([item.as_json() for item in revision.segments])),
    )
    return revision


def read_revision(connection, revision_id):
    row = connection.execute(
        'SELECT author, segments FROM score_revisions WHERE revision_id = ?', (revision_id,)
    ).fetchone()
    if row is None:
        return None
    return Revision(revision_id, row['author'], parse_segments(json.loads(row['segments'])))
