from dataclasses import dataclass

from rounds.works import ordered_round_works


@dataclass(frozen=True)
class AliasEntry:
    work_id: str
    alias: str


def allocate_aliases(works):
    return tuple(
        AliasEntry(work.work_id, f'W{number:02d}')
        for number, work in enumerate(ordered_round_works(works), start=1)
    )


def init_aliases(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS issue_aliases (
            round_id TEXT NOT NULL REFERENCES round_rosters(round_id),
            work_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            PRIMARY KEY (round_id, work_id),
            UNIQUE (round_id, alias)
        )
    ''')


def store_aliases(connection, round_id, entries):
    connection.executemany(
        'INSERT INTO issue_aliases VALUES (?, ?, ?)',
        ((round_id, entry.work_id, entry.alias) for entry in entries),
    )


def read_aliases(connection, round_id):
    rows = connection.execute(
        'SELECT work_id, alias FROM issue_aliases WHERE round_id = ? ORDER BY work_id', (round_id,)
    )
    return tuple(AliasEntry(row['work_id'], row['alias']) for row in rows)
