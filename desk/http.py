from desk.comments import init_comments, submit_comment
from desk.install import init_installs, install_bundle, read_installed_bundle
from desk.pages import init_pages, issue_page, read_page
from desk.receipts import encode_receipt, init_receipts, read_receipt_by_request, read_receipts_by_release
from festival import BusinessError, JsonRequestHandler, atomic, connect, make_server, object_fields, required_text, serve


def _query_id(query, field):
    object_fields(query, field)
    return required_text(query[field], field)


def _post_install(connection, body):
    return install_bundle(connection, body).as_json()


def _get_install(connection, query):
    return read_installed_bundle(connection, _query_id(query, 'round_id')).as_json()


def _post_comment(connection, body):
    return submit_comment(connection, body).as_json()


def _post_page(connection, body):
    return issue_page(connection, body).summary()


def _get_page(connection, query):
    return read_page(connection, _query_id(query, 'page_id')).as_json()


def _get_receipt(connection, query):
    receipt = read_receipt_by_request(connection, _query_id(query, 'request_id'))
    if receipt is None:
        raise BusinessError(404, 'receipt_not_found')
    return encode_receipt(receipt)


def _get_receipts(connection, query):
    round_id = _query_id(query, 'round_id')
    with atomic(connection, write=False):
        payload = read_installed_bundle(connection, round_id).payload
        receipts = read_receipts_by_release(connection, payload.release_id)
    return {'receipts': [encode_receipt(receipt) for receipt in receipts]}


class DeskRequestHandler(JsonRequestHandler):
    post_routes = {'/install': _post_install, '/comment': _post_comment, '/page': _post_page}
    get_routes = {
        '/install': _get_install,
        '/page': _get_page,
        '/receipt': _get_receipt,
        '/receipts': _get_receipts,
    }


def open_desk_store(database):
    connection = connect(database)
    try:
        with atomic(connection):
            for initialize in (init_installs, init_comments, init_pages, init_receipts):
                initialize(connection)
    except BaseException:
        connection.close()
        raise
    return connection


def make_desk_server(database, port=0):
    return make_server(database, port, open_desk_store, DeskRequestHandler)


def main(argv=None):
    serve('Festival review desk', make_desk_server, argv)


if __name__ == '__main__':
    main()
