from festival import BusinessError
from issue.bundles import read_bundle_by_id, read_bundle_by_round


def read_released_bundle(connection, *, release_id=None, round_id=None):
    if (release_id is None) == (round_id is None):
        raise BusinessError(422, 'choose_one_release_key')
    if release_id is not None:
        bundle = read_bundle_by_id(connection, release_id)
    else:
        bundle = read_bundle_by_round(connection, round_id)
    if bundle is None:
        raise BusinessError(404, 'release_not_found')
    return bundle


def read_expected_relations(connection, *, release_id=None, round_id=None):
    bundle = read_released_bundle(connection, release_id=release_id, round_id=round_id)
    return frozenset(bundle.payload.eligible)
