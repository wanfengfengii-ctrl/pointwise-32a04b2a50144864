from dataclasses import dataclass
import json

from archive.intake import read_verified_receipts
from archive.reconcile import compute_missing_relations, missing_result
from desk.receipts import PageReceipt, decode_receipt, encode_receipt
from festival import BusinessError, atomic, canonical_json
from issue.readback import read_released_bundle


@dataclass(frozen=True)
class Collection:
    collection_id: str
    round_id: str
    release_id: str
    pages: tuple[PageReceipt, ...]


def init_collections(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS archive_collections (
            round_id TEXT PRIMARY KEY REFERENCES round_rosters(round_id),
            collection_id TEXT NOT NULL UNIQUE,
            release_id TEXT NOT NULL UNIQUE REFERENCES issued_bundles(release_id),
            pages TEXT NOT NULL
        )
    ''')


def freeze_collection(connection, round_id):
    with atomic(connection):
        previous = read_collection_record(connection, round_id)
        if previous is not None:
            return previous
        bundle = read_released_bundle(connection, round_id=round_id)
        missing = compute_missing_relations(connection, bundle.release_id)
        if missing:
            raise BusinessError(409, 'collection_missing_pages', missing=missing_result(missing))
        pages = tuple(item.receipt for item in read_verified_receipts(connection, bundle.release_id))
        collection = Collection(f'collection-{round_id}', round_id, bundle.release_id, pages)
        connection.execute(
            'INSERT INTO archive_collections VALUES (?, ?, ?, ?)',
            (round_id, collection.collection_id, bundle.release_id, canonical_json([encode_receipt(page) for page in pages])),
        )
        return collection


def read_collection_record(connection, round_id):
    row = connection.execute('SELECT * FROM archive_collections WHERE round_id = ?', (round_id,)).fetchone()
    if row is None:
        return None
    pages = tuple(decode_receipt(page) for page in json.loads(row['pages']))
    return Collection(row['collection_id'], round_id, row['release_id'], pages)
