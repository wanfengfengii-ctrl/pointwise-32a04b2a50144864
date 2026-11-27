from festival import atomic
from issue.aliases import allocate_aliases, read_aliases, store_aliases
from issue.bundles import IssuedBundle, read_bundle_by_id, store_bundle
from issue.payload import decode_bundle_payload
from rounds.eligibility import compute_eligibility
from rounds.lifecycle import RoundReleaseState, check_release_roster, mark_round_released
from rounds.roster import build_roster, store_roster
from scores.proofs import read_proof


def release_round(connection, body):
    roster = build_roster(body)
    with atomic(connection):
        previous = check_release_roster(connection, roster)
        if previous is not None:
            return read_bundle_by_id(connection, previous.release_id)
        proofs = {work.work_id: read_proof(connection, work.proof_id) for work in roster.works}
        store_roster(connection, roster)
        store_aliases(connection, roster.round_id, allocate_aliases(roster.works))
        aliases = {entry.work_id: entry.alias for entry in read_aliases(connection, roster.round_id)}
        bundle = _project_bundle(roster, proofs, aliases)
        store_bundle(connection, bundle)
        mark_round_released(connection, RoundReleaseState(roster.round_id, bundle.release_id))
        return bundle


def _project_bundle(roster, proofs, aliases):
    relations = sorted((aliases[item.work_id], item.reviewer_id) for item in compute_eligibility(roster))
    works = []
    for work in roster.works:
        proof = proofs[work.work_id]
        works.append({
            'alias': aliases[work.work_id],
            'proof_id': proof.proof_id,
            'spans': [span.anonymous() for span in proof.spans],
        })
    payload = decode_bundle_payload({
        'release_id': f'release-{roster.round_id}',
        'round_id': roster.round_id,
        'works': works,
        'reviewers': [reviewer.reviewer_id for reviewer in roster.reviewers],
        'eligible': [{'alias': alias, 'reviewer_id': reviewer_id} for alias, reviewer_id in relations],
    })
    return IssuedBundle(payload)
