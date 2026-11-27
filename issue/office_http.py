from archive.close import freeze_collection, init_collections
from archive.intake import init_intake
from archive.readback import collection_result, get_collection
from archive.reconcile import Reconciliation, compute_missing_relations, reconcile_receipt
from festival import BusinessError, JsonRequestHandler, atomic, connect, make_server, object_fields, required_text, serve
from issue.aliases import init_aliases
from issue.bundles import init_bundles
from issue.payload import encode_bundle_payload
from issue.readback import read_released_bundle
from issue.release import release_round
from rounds.lifecycle import init_round_lifecycle
from rounds.roster import init_rosters
from scores.proofs import freeze_proof, init_proofs, read_proof
from scores.revisions import init_revisions


def _query_id(query, field):
    object_fields(query, field)
    return required_text(query[field], field)


def _post_proof(connection, body):
    return freeze_proof(connection, body).as_json()


def _get_proof(connection, query):
    return read_proof(connection, _query_id(query, 'proof_id')).as_json()


def _post_release(connection, body):
    return encode_bundle_payload(release_round(connection, body).payload)


def _get_release(connection, query):
    if set(query) == {'release_id'}:
        bundle = read_released_bundle(connection, release_id=_query_id(query, 'release_id'))
    elif set(query) == {'round_id'}:
        bundle = read_released_bundle(connection, round_id=_query_id(query, 'round_id'))
    else:
        raise BusinessError(422, 'choose_one_release_key')
    return encode_bundle_payload(bundle.payload)


def _post_reconcile(connection, body):
    object_fields(body, 'release_id', 'receipt')
    release_id = required_text(body['release_id'], 'release_id')
    return reconcile_receipt(connection, release_id, body['receipt']).as_json()


def _get_reconcile(connection, query):
    release_id = _query_id(query, 'release_id')
    with atomic(connection, write=False):
        missing = compute_missing_relations(connection, release_id)
    return Reconciliation(release_id, missing).as_json()


def _post_collection(connection, body):
    return collection_result(freeze_collection(connection, _query_id(body, 'round_id')))


def _get_collection(connection, query):
    return get_collection(connection, _query_id(query, 'round_id'))


class OfficeRequestHandler(JsonRequestHandler):
    post_routes = {
        '/proof': _post_proof,
        '/release': _post_release,
        '/reconcile': _post_reconcile,
        '/collection': _post_collection,
    }
    get_routes = {
        '/proof': _get_proof,
        '/release': _get_release,
        '/reconcile': _get_reconcile,
        '/collection': _get_collection,
    }


def open_office_store(database):
    connection = connect(database)
    initializers = (
        init_revisions, init_proofs, init_rosters, init_aliases, init_bundles,
        init_round_lifecycle, init_intake, init_collections,
    )
    try:
        with atomic(connection):
            for initialize in initializers:
                initialize(connection)
    except BaseException:
        connection.close()
        raise
    return connection


def make_office_server(database, port=0):
    return make_server(database, port, open_office_store, OfficeRequestHandler)


def main(argv=None):
    serve('Festival office', make_office_server, argv)


if __name__ == '__main__':
    main()
