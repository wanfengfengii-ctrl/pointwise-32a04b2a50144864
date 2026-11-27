from archive.dual_intake import (
    mark_decision, park_decision,
    read_parked_decisions, read_verified_decisions, read_verified_prelims,
    record_verified_prelim, structural_decision_check, verify_decision_now,
    verify_prelim_receipt,
)
from dual.designation import read_dual_designations
from dual.marks import (
    compute_disputes, remaining_dispute_windows,
)
from festival import atomic


def intake_prelim(connection, release_id, receipt_value):
    with atomic(connection):
        receipt = verify_prelim_receipt(connection, release_id, receipt_value)
        record_verified_prelim(connection, receipt)
        designation = next(
            (item for item in read_dual_designations(connection, release_id) if item['alias'] == receipt.alias),
            None,
        )
        # 出齐两页后才按实际原页重核待核首执；单页到达不触发。
        if designation is not None and _prelim_complete(connection, release_id, receipt.alias, designation):
            _replay_parked(connection, release_id, receipt.alias)
        return dual_status(connection, release_id)


def intake_decision(connection, release_id, receipt_value):
    with atomic(connection):
        receipt, designation = structural_decision_check(connection, release_id, receipt_value)
        if not _prelim_complete(connection, release_id, receipt.alias, designation):
            # 复核首执先到：先存待核，初评到齐后按实际原页重核，无需重送。
            park_decision(connection, receipt)
            return {'held': True, **dual_status(connection, release_id)}
        valid, reason = verify_decision_now(connection, release_id, receipt)
        if not valid:
            raise _conflict(reason)
        if _overlaps_verified(connection, release_id, receipt):
            raise _conflict('window_already_decided')
        mark_decision(connection, receipt.request_id, 'verified', None, receipt)
        return {'held': False, **dual_status(connection, release_id)}


def _conflict(reason):
    from festival import BusinessError
    return BusinessError(409, reason)


def _prelim_complete(connection, release_id, alias, designation):
    rows = connection.execute(
        'SELECT reviewer_id FROM verified_prelims WHERE release_id = ? AND alias = ?',
        (release_id, alias),
    ).fetchall()
    return {row['reviewer_id'] for row in rows} == set(designation['prelim_reviewers'])


def _overlaps_verified(connection, release_id, receipt):
    for earlier in read_verified_decisions(connection, release_id, receipt.alias):
        if max(earlier.window.start, receipt.window.start) < min(earlier.window.stop, receipt.window.stop):
            return True
    return False


def _replay_parked(connection, release_id, alias):
    for parked in read_parked_decisions(connection, release_id, alias):
        valid, reason = verify_decision_now(connection, release_id, parked)
        if not valid:
            # 不符的首执不能消掉待办，也不能挡住后续有效首执。
            mark_decision(connection, parked.request_id, 'rejected', reason, parked)
            continue
        if _overlaps_verified(connection, release_id, parked):
            mark_decision(connection, parked.request_id, 'rejected', 'window_already_decided', parked)
            continue
        mark_decision(connection, parked.request_id, 'verified', None, parked)


def _disputes_for(connection, release_id, alias):
    prelims = read_verified_prelims(connection, release_id, alias)
    if len(prelims) < 2:
        return None
    return compute_disputes(prelims[0].marks, prelims[1].marks)


def dual_status(connection, release_id):
    entries = []
    for designation in read_dual_designations(connection, release_id):
        alias = designation['alias']
        prelims = read_verified_prelims(connection, release_id, alias)
        present = {receipt.reviewer_id for receipt in prelims}
        missing_prelim = sorted(set(designation['prelim_reviewers']) - present)
        disputes = _disputes_for(connection, release_id, alias)
        undecided = []
        if disputes is not None:
            decided = tuple(item.window for item in read_verified_decisions(connection, release_id, alias))
            undecided = [window.as_json() for window in remaining_dispute_windows(disputes, decided)]
        entries.append({
            'alias': alias,
            'missing_prelim': missing_prelim,
            'undecided_windows': undecided,
        })
    return {'dual_review': entries}


def dual_missing_relations(connection, release_id):
    missing = []
    for designation in read_dual_designations(connection, release_id):
        alias = designation['alias']
        present = {receipt.reviewer_id for receipt in read_verified_prelims(connection, release_id, alias)}
        for reviewer_id in designation['prelim_reviewers']:
            if reviewer_id not in present:
                missing.append((alias, reviewer_id))
    return tuple(sorted(missing))


def dual_blocking_items(connection, release_id):
    """Return (missing prelim relations, undecided dispute windows) for closing."""
    missing = []
    undecided = []
    for designation in read_dual_designations(connection, release_id):
        alias = designation['alias']
        present = {receipt.reviewer_id for receipt in read_verified_prelims(connection, release_id, alias)}
        for reviewer_id in designation['prelim_reviewers']:
            if reviewer_id not in present:
                missing.append({'alias': alias, 'reviewer_id': reviewer_id})
        disputes = _disputes_for(connection, release_id, alias)
        if disputes is None:
            continue
        decided = tuple(item.window for item in read_verified_decisions(connection, release_id, alias))
        for window in remaining_dispute_windows(disputes, decided):
            undecided.append({'alias': alias, 'window': window.as_json()})
    return missing, undecided
