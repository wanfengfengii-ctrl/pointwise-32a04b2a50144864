from dataclasses import dataclass
import json

from festival import BusinessError, atomic, canonical_json, required_text
from issue.payload import BundlePayload, decode_bundle_payload, encode_bundle_payload


@dataclass(frozen=True)
class InstalledBundle:
    receipt_id: str
    payload: BundlePayload

    def as_json(self):
        return {'receipt_id': self.receipt_id, 'bundle': encode_bundle_payload(self.payload)}


def init_installs(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS desk_installs (
            release_id TEXT PRIMARY KEY,
            round_id TEXT NOT NULL UNIQUE,
            receipt_id TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL
        )
    ''')


def install_bundle(connection, body):
    release_id = required_text(body.get('release_id') if isinstance(body, dict) else None, 'release_id')
    with atomic(connection):
        previous = connection.execute(
            'SELECT * FROM desk_installs WHERE release_id = ?', (release_id,)
        ).fetchone()
        if previous is not None:
            if canonical_json(body) != previous['payload']:
                raise BusinessError(409, 'installed_bundle_conflict')
            return _from_row(previous)
        payload = decode_bundle_payload(body)
        previous_round = connection.execute(
            'SELECT release_id FROM desk_installs WHERE round_id = ?', (payload.round_id,)
        ).fetchone()
        if previous_round is not None:
            raise BusinessError(409, 'installed_round_conflict')
        receipt_id = f'install-{release_id}'
        connection.execute(
            'INSERT INTO desk_installs VALUES (?, ?, ?, ?)',
            (release_id, payload.round_id, receipt_id, canonical_json(encode_bundle_payload(payload))),
        )
        return InstalledBundle(receipt_id, payload)


def read_installed_bundle(connection, round_id):
    row = connection.execute('SELECT * FROM desk_installs WHERE round_id = ?', (round_id,)).fetchone()
    if row is None:
        raise BusinessError(404, 'install_not_found')
    return _from_row(row)


def _from_row(row):
    return InstalledBundle(row['receipt_id'], decode_bundle_payload(json.loads(row['payload'])))
