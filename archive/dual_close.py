import json

from archive.dual_intake import read_verified_decisions, read_verified_prelims
from archive.dual_reconcile import dual_blocking_items
from dual.designation import read_dual_designations
from dual.marks import compute_disputes
from festival import BusinessError, atomic, canonical_json
from issue.readback import read_released_bundle


def init_dual_collections(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS dual_collections (
            round_id TEXT PRIMARY KEY REFERENCES round_rosters(round_id),
            release_id TEXT NOT NULL UNIQUE,
            record TEXT NOT NULL
        )
    ''')


def build_dual_record(connection, release_id):
    entries = []
    for designation in read_dual_designations(connection, release_id):
        alias = designation['alias']
        prelims = sorted(read_verified_prelims(connection, release_id, alias), key=lambda item: item.reviewer_id)
        prelim_pages = [
            {
                'reviewer_id': receipt.reviewer_id,
                'page_id': receipt.page_id,
                'request_id': receipt.request_id,
                'marks': [entry.as_json() for entry in receipt.marks],
            }
            for receipt in prelims
        ]
        disputes = compute_disputes(prelims[0].marks, prelims[1].marks)
        decisions = sorted(read_verified_decisions(connection, release_id, alias), key=lambda item: item.window.start)
        entries.append({
            'alias': alias,
            'adjudicator': designation['adjudicator'],
            'prelim_pages': prelim_pages,
            'disputes': [dispute.as_json() for dispute in disputes],
            'decisions': [
                {
                    'request_id': item.request_id,
                    'decision_id': item.decision_id,
                    'window': item.window.as_json(),
                    'mark': item.mark,
                }
                for item in decisions
            ],
        })
    return entries


def freeze_dual_collection(connection, round_id):
    with atomic(connection):
        bundle = read_released_bundle(connection, round_id=round_id)
        release_id = bundle.release_id
        existing = connection.execute(
            'SELECT record FROM dual_collections WHERE round_id = ?', (round_id,)
        ).fetchone()
        if existing is not None:
            return json.loads(existing['record'])
        if not read_dual_designations(connection, release_id):
            return None
        missing, undecided = dual_blocking_items(connection, release_id)
        if missing or undecided:
            raise BusinessError(
                409, 'dual_collection_incomplete',
                missing_prelim=missing, undecided_windows=undecided,
            )
        record = {'round_id': round_id, 'release_id': release_id, 'dual_review': build_dual_record(connection, release_id)}
        connection.execute(
            'INSERT INTO dual_collections VALUES (?, ?, ?)',
            (round_id, release_id, canonical_json(record)),
        )
        return record


def read_dual_collection(connection, round_id):
    row = connection.execute(
        'SELECT record FROM dual_collections WHERE round_id = ?', (round_id,)
    ).fetchone()
    if row is None:
        return None
    return json.loads(row['record'])
