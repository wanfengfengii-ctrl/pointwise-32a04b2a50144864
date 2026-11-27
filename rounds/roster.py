from dataclasses import dataclass
import json

from festival import BusinessError, array, canonical_json, object_fields, required_text
from rounds.works import RoundWork, parse_round_works


@dataclass(frozen=True)
class Reviewer:
    reviewer_id: str
    group: str

    def as_json(self):
        return {'reviewer_id': self.reviewer_id, 'group': self.group}


@dataclass(frozen=True)
class RosterSnapshot:
    round_id: str
    works: tuple[RoundWork, ...]
    reviewers: tuple[Reviewer, ...]


def build_roster(body):
    object_fields(body, 'round_id', 'works', 'reviewers')
    round_id = required_text(body['round_id'], 'round_id')
    reviewers = {}
    for item in array(body['reviewers'], 'reviewers'):
        object_fields(item, 'reviewer_id', 'group')
        reviewer_id = required_text(item['reviewer_id'], 'reviewer_id')
        if reviewer_id in reviewers:
            raise BusinessError(422, 'duplicate_reviewer', reviewer_id=reviewer_id)
        reviewers[reviewer_id] = Reviewer(reviewer_id, required_text(item['group'], 'group'))
    return RosterSnapshot(
        round_id, parse_round_works(body['works']), tuple(reviewers[key] for key in sorted(reviewers))
    )


def same_roster(left, right):
    return left == right


def init_rosters(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS round_rosters (
            round_id TEXT PRIMARY KEY,
            works TEXT NOT NULL,
            reviewers TEXT NOT NULL
        )
    ''')


def store_roster(connection, roster):
    connection.execute(
        'INSERT INTO round_rosters VALUES (?, ?, ?)',
        (
            roster.round_id,
            canonical_json([work.as_json() for work in roster.works]),
            canonical_json([reviewer.as_json() for reviewer in roster.reviewers]),
        ),
    )


def read_roster(connection, round_id):
    row = connection.execute(
        'SELECT works, reviewers FROM round_rosters WHERE round_id = ?', (round_id,)
    ).fetchone()
    if row is None:
        return None
    return build_roster({'round_id': round_id, 'works': json.loads(row['works']), 'reviewers': json.loads(row['reviewers'])})
