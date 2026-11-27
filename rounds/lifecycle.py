from dataclasses import dataclass

from festival import BusinessError
from rounds.roster import read_roster, same_roster


@dataclass(frozen=True)
class RoundReleaseState:
    round_id: str
    release_id: str


def init_round_lifecycle(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS round_releases (
            round_id TEXT PRIMARY KEY REFERENCES round_rosters(round_id),
            release_id TEXT NOT NULL UNIQUE REFERENCES issued_bundles(release_id)
        )
    ''')


def read_round_release(connection, round_id):
    row = connection.execute(
        'SELECT release_id FROM round_releases WHERE round_id = ?', (round_id,)
    ).fetchone()
    if row is None:
        return None
    return RoundReleaseState(round_id, row['release_id'])


def check_release_roster(connection, roster):
    previous = read_round_release(connection, roster.round_id)
    if previous is not None and not same_roster(read_roster(connection, roster.round_id), roster):
        raise BusinessError(409, 'roster_conflict')
    return previous


def mark_round_released(connection, state):
    connection.execute('INSERT INTO round_releases VALUES (?, ?)', (state.round_id, state.release_id))
