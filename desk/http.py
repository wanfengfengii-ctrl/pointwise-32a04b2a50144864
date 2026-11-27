from desk.comments import init_comments, submit_comment
from desk.dual_pages import init_prelim_pages, issue_prelim_page, read_prelim_page
from desk.dual_receipts import (
    init_decision_receipts, init_dual_receipts,
    read_decision_by_request, read_prelim_receipt_by_request,
)
from desk.dual_review import dispute_view, issue_decision
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


def _post_preliminary(connection, body):
    page = issue_prelim_page(connection, body, _write_prelim_receipt, read_prelim_receipt_by_request)
    return page.summary()


def _write_prelim_receipt(connection, request_id, page):
    from desk.dual_receipts import write_prelim_receipt
    write_prelim_receipt(connection, request_id, page)


def _get_prelim_page(connection, query):
    return read_prelim_page(connection, _query_id(query, 'page_id')).content()


def _get_prelim_receipt(connection, query):
    receipt = read_prelim_receipt_by_request(connection, _query_id(query, 'request_id'))
    if receipt is None:
        raise BusinessError(404, 'receipt_not_found')
    return receipt.as_json()


def _get_dispute(connection, query):
    object_fields(query, 'round_id', 'alias')
    return dispute_view(connection, required_text(query['round_id'], 'round_id'),
                        required_text(query['alias'], 'alias'))


def _post_decision(connection, body):
    return issue_decision(connection, body)


def _get_decision(connection, query):
    receipt = read_decision_by_request(connection, _query_id(query, 'request_id'))
    if receipt is None:
        raise BusinessError(404, 'receipt_not_found')
    return receipt.as_json()


class DeskRequestHandler(JsonRequestHandler):
    post_routes = {
        '/install': _post_install,
        '/comment': _post_comment,
        '/page': _post_page,
        '/preliminary': _post_preliminary,
        '/decision': _post_decision,
    }
    get_routes = {
        '/install': _get_install,
        '/page': _get_page,
        '/receipt': _get_receipt,
        '/receipts': _get_receipts,
        '/prelim-page': _get_prelim_page,
        '/prelim-receipt': _get_prelim_receipt,
        '/dispute': _get_dispute,
        '/decision': _get_decision,
    }


def open_desk_store(database):
    connection = connect(database)
    try:
        with atomic(connection):
            for initialize in (
                init_installs, init_comments, init_pages, init_receipts,
                init_prelim_pages, init_dual_receipts, init_decision_receipts,
            ):
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
