from dataclasses import dataclass
import json

from festival import BusinessError, array, canonical_json, object_fields, required_text
from rounds.roster import RosterSnapshot


@dataclass(frozen=True)
class DualDesignation:
    work_id: str
    prelim_reviewers: tuple[str, str]
    adjudicator: str

    def as_json(self):
        return {
            'work_id': self.work_id,
            'prelim_reviewers': list(self.prelim_reviewers),
            'adjudicator': self.adjudicator,
        }


def parse_dual_designations(value, roster: RosterSnapshot):
    if value is None:
        return ()
    entries = []
    work_groups = {work.work_id: work.group for work in roster.works}
    reviewer_groups = {reviewer.reviewer_id: reviewer.group for reviewer in roster.reviewers}
    seen = set()
    for item in array(value, 'dual_review'):
        object_fields(item, 'work_id', 'prelim_reviewers', 'adjudicator')
        work_id = required_text(item['work_id'], 'work_id')
        if work_id not in work_groups or work_id in seen:
            raise BusinessError(422, 'invalid_dual_work')
        prelim = tuple(required_text(part, 'prelim_reviewers') for part in array(item['prelim_reviewers'], 'prelim_reviewers'))
        if len(prelim) != 2 or prelim[0] == prelim[1]:
            raise BusinessError(422, 'invalid_dual_prelim_reviewers')
        adjudicator = required_text(item['adjudicator'], 'adjudicator')
        people = (*prelim, adjudicator)
        if len(set(people)) != 3 or any(person not in reviewer_groups for person in people):
            raise BusinessError(422, 'invalid_dual_reviewer')
        # 回避资格：三位复核人都不能与作品同组。
        if any(reviewer_groups[person] == work_groups[work_id] for person in people):
            raise BusinessError(422, 'dual_reviewer_not_recused')
        seen.add(work_id)
        entries.append(DualDesignation(work_id, prelim, adjudicator))
    return tuple(sorted(entries, key=lambda entry: entry.work_id))


def init_dual_designations(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS dual_designations (
            release_id TEXT NOT NULL REFERENCES issued_bundles(release_id),
            work_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            prelim_reviewers TEXT NOT NULL,
            adjudicator TEXT NOT NULL,
            PRIMARY KEY (release_id, work_id)
        )
    ''')


def store_dual_designations(connection, release_id, entries, aliases):
    connection.executemany(
        'INSERT INTO dual_designations VALUES (?, ?, ?, ?, ?)',
        (
            (
                release_id,
                entry.work_id,
                aliases[entry.work_id],
                canonical_json(list(entry.prelim_reviewers)),
                entry.adjudicator,
            )
            for entry in entries
        ),
    )


def read_dual_designations(connection, release_id):
    rows = connection.execute(
        'SELECT work_id, alias, prelim_reviewers, adjudicator FROM dual_designations '
        'WHERE release_id = ? ORDER BY alias',
        (release_id,),
    )
    return tuple(
        {
            'work_id': row['work_id'],
            'alias': row['alias'],
            'prelim_reviewers': tuple(json.loads(row['prelim_reviewers'])),
            'adjudicator': row['adjudicator'],
        }
        for row in rows
    )
