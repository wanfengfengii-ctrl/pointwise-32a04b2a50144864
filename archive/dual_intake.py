import json

from desk.dual_receipts import decode_decision_receipt, decode_prelim_receipt
from desk.dual_pages import prelim_page_id
from dual.designation import read_dual_designations
from dual.marks import compute_disputes, dispute_windows
from festival import BusinessError, canonical_json
from issue.readback import read_released_bundle


def init_dual_intake(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS verified_prelims (
            page_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL UNIQUE,
            release_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,
            receipt TEXT NOT NULL,
            UNIQUE (release_id, alias, reviewer_id)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS intake_decisions (
            request_id TEXT PRIMARY KEY,
            release_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT,
            receipt TEXT NOT NULL
        )
    ''')


def _dual_map(connection, release_id):
    bundle = read_released_bundle(connection, release_id=release_id)
    designations = {entry['alias']: entry for entry in read_dual_designations(connection, release_id)}
    return bundle, designations


def verify_prelim_receipt(connection, release_id, value):
    receipt = decode_prelim_receipt(value)
    if receipt.release_id != release_id:
        raise BusinessError(409, 'receipt_release_mismatch')
    bundle, designations = _dual_map(connection, release_id)
    if receipt.round_id != bundle.payload.round_id:
        raise BusinessError(409, 'receipt_round_mismatch')
    designation = designations.get(receipt.alias)
    if designation is None or receipt.reviewer_id not in designation['prelim_reviewers']:
        raise BusinessError(409, 'receipt_relation_mismatch')
    excerpt = bundle.payload.excerpt_for(receipt.alias)
    if receipt.proof_id != excerpt.proof_id:
        raise BusinessError(409, 'receipt_excerpt_mismatch')
    for entry in receipt.marks:
        if not excerpt.covers_window(entry.window):
            raise BusinessError(409, 'receipt_excerpt_mismatch')
    if prelim_page_id(_prelim_content(receipt)) != receipt.page_id:
        raise BusinessError(409, 'receipt_page_mismatch')
    return receipt


def _prelim_content(receipt):
    return {
        'release_id': receipt.release_id,
        'round_id': receipt.round_id,
        'alias': receipt.alias,
        'reviewer_id': receipt.reviewer_id,
        'proof_id': receipt.proof_id,
        'marks': [entry.as_json() for entry in receipt.marks],
    }


def record_verified_prelim(connection, receipt):
    encoded = canonical_json(receipt.as_json())
    previous = connection.execute('''
        SELECT receipt FROM verified_prelims
        WHERE page_id = ? OR request_id = ? OR (release_id = ? AND alias = ? AND reviewer_id = ?)
    ''', (receipt.page_id, receipt.request_id, receipt.release_id, receipt.alias, receipt.reviewer_id)).fetchone()
    if previous is not None:
        if encoded != previous['receipt']:
            raise BusinessError(409, 'verified_receipt_conflict')
        return
    connection.execute(
        'INSERT INTO verified_prelims VALUES (?, ?, ?, ?, ?, ?)',
        (receipt.page_id, receipt.request_id, receipt.release_id, receipt.alias, receipt.reviewer_id, encoded),
    )


def read_verified_prelims(connection, release_id, alias=None):
    sql = 'SELECT receipt FROM verified_prelims WHERE release_id = ?'
    parameters = [release_id]
    if alias is not None:
        sql += ' AND alias = ?'
        parameters.append(alias)
    sql += ' ORDER BY alias, reviewer_id'
    rows = connection.execute(sql, parameters)
    return tuple(decode_prelim_receipt(json.loads(row['receipt'])) for row in rows)


def _prelim_complete(connection, release_id, alias, designation):
    rows = connection.execute(
        'SELECT reviewer_id FROM verified_prelims WHERE release_id = ? AND alias = ?',
        (release_id, alias),
    ).fetchall()
    present = {row['reviewer_id'] for row in rows}
    return present == set(designation['prelim_reviewers'])


def verify_decision_now(connection, release_id, receipt):
    """Full verification once both prelim pages are present."""
    bundle, designations = _dual_map(connection, release_id)
    designation = designations.get(receipt.alias)
    if designation is None or receipt.adjudicator != designation['adjudicator']:
        return False, 'receipt_relation_mismatch'
    excerpt = bundle.payload.excerpt_for(receipt.alias)
    if receipt.round_id != bundle.payload.round_id:
        return False, 'receipt_round_mismatch'
    if receipt.proof_id != excerpt.proof_id or not excerpt.covers_window(receipt.window):
        return False, 'receipt_excerpt_mismatch'
    prelims = read_verified_prelims(connection, release_id, receipt.alias)
    disputes = compute_disputes(prelims[0].marks, prelims[1].marks)
    scope = dispute_windows(disputes)
    if not any(piece.start <= receipt.window.start and receipt.window.stop <= piece.stop for piece in scope):
        return False, 'outside_dispute_scope'
    return True, None


def structural_decision_check(connection, release_id, value):
    """Checks available before the prelim pages arrive; parks the receipt otherwise."""
    receipt = decode_decision_receipt(value)
    if receipt.release_id != release_id:
        raise BusinessError(409, 'receipt_release_mismatch')
    bundle, designations = _dual_map(connection, release_id)
    if receipt.round_id != bundle.payload.round_id:
        raise BusinessError(409, 'receipt_round_mismatch')
    designation = designations.get(receipt.alias)
    if designation is None or receipt.adjudicator != designation['adjudicator']:
        raise BusinessError(409, 'receipt_relation_mismatch')
    excerpt = bundle.payload.excerpt_for(receipt.alias)
    if receipt.proof_id != excerpt.proof_id or not excerpt.covers_window(receipt.window):
        raise BusinessError(409, 'receipt_excerpt_mismatch')
    return receipt, designation


def park_decision(connection, receipt):
    encoded = canonical_json(receipt.as_json())
    connection.execute(
        'INSERT INTO intake_decisions (request_id, release_id, alias, status, reason, receipt) VALUES (?, ?, ?, ?, ?, ?)',
        (receipt.request_id, receipt.release_id, receipt.alias, 'parked', None, encoded),
    )


def read_parked_decisions(connection, release_id, alias):
    rows = connection.execute(
        "SELECT receipt FROM intake_decisions WHERE release_id = ? AND alias = ? AND status = 'parked' ORDER BY rowid",
        (release_id, alias),
    )
    return tuple(decode_decision_receipt(json.loads(row['receipt'])) for row in rows)


def mark_decision(connection, request_id, status, reason, receipt):
    encoded = canonical_json(receipt.as_json())
    connection.execute('''
        INSERT INTO intake_decisions (request_id, release_id, alias, status, reason, receipt)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(request_id) DO UPDATE SET
            status = excluded.status,
            reason = excluded.reason,
            receipt = excluded.receipt
    ''', (request_id, receipt.release_id, receipt.alias, status, reason, encoded))


def read_intake_decisions(connection, release_id):
    rows = connection.execute(
        'SELECT request_id, status, reason, receipt FROM intake_decisions WHERE release_id = ? ORDER BY rowid',
        (release_id,),
    )
    return tuple(
        {
            'request_id': row['request_id'],
            'status': row['status'],
            'reason': row['reason'],
            'receipt': decode_decision_receipt(json.loads(row['receipt'])),
        }
        for row in rows
    )


def read_verified_decisions(connection, release_id, alias=None):
    sql = "SELECT receipt FROM intake_decisions WHERE release_id = ? AND status = 'verified'"
    parameters = [release_id]
    if alias is not None:
        sql += ' AND alias = ?'
        parameters.append(alias)
    sql += ' ORDER BY rowid'
    rows = connection.execute(sql, parameters)
    return tuple(decode_decision_receipt(json.loads(row['receipt'])) for row in rows)


def is_dual_alias(connection, release_id, alias):
    return any(entry['alias'] == alias for entry in read_dual_designations(connection, release_id))
