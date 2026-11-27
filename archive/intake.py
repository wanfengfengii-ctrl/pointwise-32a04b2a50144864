from dataclasses import dataclass
import json

from desk.receipts import PageReceipt, decode_receipt, encode_receipt, formal_page_id
from festival import BusinessError, canonical_json, serial_number
from issue.readback import read_released_bundle


@dataclass(frozen=True)
class VerifiedReceipt:
    receipt: PageReceipt

    @property
    def relation(self):
        return self.receipt.alias, self.receipt.reviewer_id


def init_intake(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS verified_receipts (
            page_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL UNIQUE,
            release_id TEXT NOT NULL REFERENCES issued_bundles(release_id),
            alias TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,
            receipt TEXT NOT NULL,
            UNIQUE (release_id, alias, reviewer_id)
        )
    ''')


def verify_receipt(connection, release_id, value):
    receipt = decode_receipt(value)
    if receipt.release_id != release_id:
        raise BusinessError(409, 'receipt_release_mismatch')
    payload = read_released_bundle(connection, release_id=release_id).payload
    if receipt.round_id != payload.round_id:
        raise BusinessError(409, 'receipt_round_mismatch')
    if (receipt.alias, receipt.reviewer_id) not in payload.eligible:
        raise BusinessError(409, 'receipt_relation_mismatch')
    excerpt = payload.excerpt_for(receipt.alias)
    if receipt.proof_id != excerpt.proof_id or not excerpt.covers_window(receipt.window):
        raise BusinessError(409, 'receipt_excerpt_mismatch')
    if serial_number('draft', receipt.draft_id) is None or formal_page_id(receipt.page_content()) != receipt.page_id:
        raise BusinessError(409, 'receipt_page_mismatch')
    return VerifiedReceipt(receipt)


def record_verified_receipt(connection, verified):
    receipt = verified.receipt
    encoded = canonical_json(encode_receipt(receipt))
    previous = connection.execute('''
        SELECT receipt FROM verified_receipts
        WHERE page_id = ? OR request_id = ? OR (release_id = ? AND alias = ? AND reviewer_id = ?)
    ''', (receipt.page_id, receipt.request_id, receipt.release_id, receipt.alias, receipt.reviewer_id)).fetchone()
    if previous is not None:
        if encoded != previous['receipt']:
            raise BusinessError(409, 'verified_receipt_conflict')
        return
    connection.execute(
        'INSERT INTO verified_receipts VALUES (?, ?, ?, ?, ?, ?)',
        (receipt.page_id, receipt.request_id, receipt.release_id, receipt.alias, receipt.reviewer_id, encoded),
    )


def read_verified_receipts(connection, release_id):
    rows = connection.execute('''
        SELECT receipt FROM verified_receipts WHERE release_id = ? ORDER BY alias, reviewer_id
    ''', (release_id,))
    return tuple(VerifiedReceipt(decode_receipt(json.loads(row['receipt']))) for row in rows)
