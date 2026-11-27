from archive.close import read_collection_record
from desk.receipts import encode_receipt
from festival import BusinessError


def get_collection(connection, round_id):
    collection = read_collection_record(connection, round_id)
    if collection is None:
        raise BusinessError(404, 'collection_not_found')
    return collection_result(collection)


def collection_result(collection):
    return {
        'collection_id': collection.collection_id,
        'round_id': collection.round_id,
        'release_id': collection.release_id,
        'pages': [encode_receipt(page) for page in collection.pages],
    }
