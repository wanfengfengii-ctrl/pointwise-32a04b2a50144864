from festival import atomic
from dual.designation import parse_dual_designations, store_dual_designations
from issue.aliases import allocate_aliases, read_aliases, store_aliases
from issue.bundles import IssuedBundle, read_bundle_by_id, store_bundle
from issue.payload import decode_bundle_payload
from rounds.eligibility import compute_eligibility
from rounds.lifecycle import RoundReleaseState, check_release_roster, mark_round_released
from rounds.roster import build_roster, store_roster
from scores.proofs import read_proof


def release_round(connection, body):
    roster = build_roster(body)
    designations = parse_dual_designations(body.get('dual_review'), roster)
    with atomic(connection):
        previous = check_release_roster(connection, roster)
        if previous is not None:
            return read_bundle_by_id(connection, previous.release_id)
        proofs = {work.work_id: read_proof(connection, work.proof_id) for work in roster.works}
        store_roster(connection, roster)
        store_aliases(connection, roster.round_id, allocate_aliases(roster.works))
        aliases = {entry.work_id: entry.alias for entry in read_aliases(connection, roster.round_id)}
        bundle = _project_bundle(roster, proofs, aliases, designations)
        store_bundle(connection, bundle)
        store_dual_designations(connection, bundle.release_id, designations, aliases)
        mark_round_released(connection, RoundReleaseState(roster.round_id, bundle.release_id))
        return bundle


def _restricted_eligibility(roster, designations):
    locked_works = {entry.work_id: set(entry.prelim_reviewers) for entry in designations}
    relations = set()
    for relation in compute_eligibility(roster):
        allowed = locked_works.get(relation.work_id)
        if allowed is None or relation.reviewer_id in allowed:
            relations.add((None, relation.work_id, relation.reviewer_id))
    return frozenset((work_id, reviewer_id) for _, work_id, reviewer_id in relations)


def _project_bundle(roster, proofs, aliases, designations):
    relations = sorted((aliases[work_id], reviewer_id) for work_id, reviewer_id in _restricted_eligibility(roster, designations))
    works = []
    for work in roster.works:
        proof = proofs[work.work_id]
        works.append({
            'alias': aliases[work.work_id],
            'proof_id': proof.proof_id,
            'spans': [span.anonymous() for span in proof.spans],
        })
    dual_payload = [
        {
            'alias': aliases[entry.work_id],
            'prelim_reviewers': list(entry.prelim_reviewers),
            'adjudicator': entry.adjudicator,
        }
        for entry in designations
    ]
    payload = decode_bundle_payload({
        'release_id': f'release-{roster.round_id}',
        'round_id': roster.round_id,
        'works': works,
        'reviewers': [reviewer.reviewer_id for reviewer in roster.reviewers],
        'eligible': [{'alias': alias, 'reviewer_id': reviewer_id} for alias, reviewer_id in relations],
        **({'dual_review': dual_payload} if dual_payload else {}),
    })
    return IssuedBundle(payload)
