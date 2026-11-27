from hashlib import sha256
import json

from desk.dual_pages import read_prelim_pages_for_alias
from desk.dual_receipts import read_decision_by_request
from desk.install import read_installed_bundle
from dual.marks import compute_disputes, dispute_windows, remaining_dispute_windows
from festival import BusinessError, atomic, canonical_json, object_fields, required_text
from scores.windows import parse_beat_window


def _designation_for_alias(payload, alias):
    return payload.dual_for_alias(alias)


def dispute_view(connection, round_id, alias):
    with atomic(connection, write=False):
        payload = read_installed_bundle(connection, round_id).payload
        designation = _designation_for_alias(payload, alias)
        if designation is None:
            raise BusinessError(404, 'dual_work_not_found')
        pages = read_prelim_pages_for_alias(connection, payload.release_id, alias)
        excerpt = payload.excerpt_for(alias)
        if len(pages) < 2:
            return {
                'alias': alias,
                'status': 'awaiting_prelim',
                'excerpt': excerpt.as_json(),
                'windows': [],
            }
        disputes = compute_disputes(pages[0].marks, pages[1].marks)
        decided = _decided_windows(connection, payload.release_id, alias)
        windows = remaining_dispute_windows(disputes, decided)
        return {
            'alias': alias,
            'status': 'open' if windows else 'cleared',
            'excerpt': excerpt.as_json(),
            'windows': [window.as_json() for window in windows],
        }


def _decided_windows(connection, release_id, alias):
    rows = connection.execute(
        'SELECT window FROM decision_receipts WHERE release_id = ? AND alias = ?',
        (release_id, alias),
    )
    return tuple(parse_beat_window(json.loads(row['window'])) for row in rows)


def issue_decision(connection, body):
    fields = ('round_id', 'alias', 'adjudicator', 'window', 'mark', 'request_id')
    object_fields(body, *fields)
    round_id = required_text(body['round_id'], 'round_id')
    alias = required_text(body['alias'], 'alias')
    adjudicator = required_text(body['adjudicator'], 'adjudicator')
    request_id = required_text(body['request_id'], 'request_id')
    window = parse_beat_window(body['window'])
    if body['mark'] not in ('pass', 'redo'):
        raise BusinessError(422, 'invalid_mark')
    mark = body['mark']
    with atomic(connection):
        previous = read_decision_by_request(connection, request_id)
        if previous is not None:
            if previous.original_parameters() != (round_id, alias, adjudicator, window, mark):
                raise BusinessError(409, 'decision_request_conflict')
            return {'decision_id': previous.decision_id, 'request_id': request_id}

        payload = read_installed_bundle(connection, round_id).payload
        designation = _designation_for_alias(payload, alias)
        if designation is None or adjudicator != designation['adjudicator']:
            raise BusinessError(409, 'not_dual_adjudicator')
        pages = read_prelim_pages_for_alias(connection, payload.release_id, alias)
        if len(pages) < 2:
            raise BusinessError(409, 'prelim_incomplete')
        disputes = compute_disputes(pages[0].marks, pages[1].marks)
        scope = dispute_windows(disputes)
        if not scope or not _within_scope(window, scope):
            raise BusinessError(422, 'outside_dispute_scope')
        decided = _decided_windows(connection, payload.release_id, alias)
        if not _is_unadjudicated(window, decided):
            raise BusinessError(409, 'window_already_decided')

        decision_id = _decision_id(payload.release_id, alias, adjudicator, window, mark)
        connection.execute(
            'INSERT INTO decision_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (
                decision_id, payload.release_id, round_id, alias, adjudicator,
                payload.excerpt_for(alias).proof_id, canonical_json(window.as_json()), mark,
            ),
        )
        connection.execute(
            'INSERT INTO decision_requests VALUES (?, ?)', (request_id, decision_id)
        )
        return {'decision_id': decision_id, 'request_id': request_id}


def _within_scope(window, scope):
    return any(piece.start <= window.start and window.stop <= piece.stop for piece in scope)


def _is_unadjudicated(window, decided):
    # The sub-window must not overlap any prior decision within the dispute scope.
    for earlier in decided:
        if max(earlier.start, window.start) < min(earlier.stop, window.stop):
            return False
    return True


def _decision_id(release_id, alias, adjudicator, window, mark):
    digest = sha256(
        canonical_json({
            'release_id': release_id, 'alias': alias, 'adjudicator': adjudicator,
            'window': window.as_json(), 'mark': mark,
        }).encode('utf-8')
    ).hexdigest()
    return f'decision-{digest}'
