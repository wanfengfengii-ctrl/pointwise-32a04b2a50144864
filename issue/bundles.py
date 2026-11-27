from dataclasses import dataclass
import json

from festival import canonical_json
from issue.payload import BundlePayload, decode_bundle_payload, encode_bundle_payload


@dataclass(frozen=True)
class IssuedBundle:
    payload: BundlePayload

    @property
    def release_id(self):
        return self.payload.release_id

    @property
    def round_id(self):
        return self.payload.round_id


def init_bundles(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS issued_bundles (
            release_id TEXT PRIMARY KEY,
            round_id TEXT NOT NULL UNIQUE REFERENCES round_rosters(round_id),
            payload TEXT NOT NULL
        )
    ''')


def store_bundle(connection, bundle):
    connection.execute(
        'INSERT INTO issued_bundles VALUES (?, ?, ?)',
        (bundle.release_id, bundle.round_id, canonical_json(encode_bundle_payload(bundle.payload))),
    )


def read_bundle_by_id(connection, release_id):
    row = connection.execute(
        'SELECT payload FROM issued_bundles WHERE release_id = ?', (release_id,)
    ).fetchone()
    return _bundle_from_row(row)


def read_bundle_by_round(connection, round_id):
    row = connection.execute(
        'SELECT payload FROM issued_bundles WHERE round_id = ?', (round_id,)
    ).fetchone()
    return _bundle_from_row(row)


def _bundle_from_row(row):
    if row is None:
        return None
    return IssuedBundle(decode_bundle_payload(json.loads(row['payload'])))
