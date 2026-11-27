import argparse
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sqlite3
from urllib.parse import parse_qsl, urlsplit


class BusinessError(Exception):
    def __init__(self, status, code, **details):
        super().__init__(code)
        self.status = status
        self.payload = {'error': code, **details}


def object_fields(value, *fields):
    if not isinstance(value, dict) or value.keys() != set(fields):
        raise BusinessError(422, 'invalid_fields', fields=list(fields))
    return value


def required_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise BusinessError(422, 'invalid_text', field=field)
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        raise BusinessError(422, 'invalid_text', field=field) from None
    return value


def array(value, field):
    if not isinstance(value, list):
        raise BusinessError(422, 'invalid_array', field=field)
    return value


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def serial_id(prefix, serial):
    return f'{prefix}-{serial}'


def serial_number(prefix, identifier):
    number_prefix = f'{prefix}-'
    if not isinstance(identifier, str) or not identifier.startswith(number_prefix):
        return None
    digits = identifier[len(number_prefix):]
    if not (0 < len(digits) <= 19 and digits.isascii() and digits.isdecimal()):
        return None
    number = int(digits)
    if 0 < number <= 2**63 - 1 and str(number) == digits:
        return number
    return None


def connect(database):
    connection = sqlite3.connect(database, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    return connection


@contextmanager
def atomic(connection, *, write=True):
    connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
    try:
        yield
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


class JsonRequestHandler(BaseHTTPRequestHandler):
    get_routes = {}
    post_routes = {}

    def do_GET(self):
        self.dispatch('GET')

    def do_POST(self):
        self.dispatch('POST')

    def dispatch(self, method):
        try:
            target = urlsplit(self.path)
        except ValueError:
            self.write_result(400, {'error': 'invalid_target'})
            return
        routes = self.get_routes if method == 'GET' else self.post_routes
        action = routes.get(target.path)
        if action is None:
            self.write_result(404, {'error': 'unknown_endpoint'})
            return
        try:
            parameters = self.read_query(target.query) if method == 'GET' else self.read_body()
            with closing(connect(self.server.database)) as connection:
                result = action(connection, parameters)
        except BusinessError as error:
            self.write_result(error.status, error.payload)
        else:
            self.write_result(200, result)

    def read_query(self, query):
        try:
            pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True, errors='strict')
        except ValueError:
            raise BusinessError(400, 'invalid_query') from None
        parameters = dict(pairs)
        if len(parameters) != len(pairs):
            raise BusinessError(400, 'invalid_query')
        return parameters

    def read_body(self):
        try:
            size = int(self.headers['Content-Length'])
            if size < 1:
                raise ValueError('empty request')
            return json.loads(self.rfile.read(size).decode('utf-8'))
        except (TypeError, ValueError, OverflowError, RecursionError):
            raise BusinessError(400, 'invalid_json') from None

    def write_result(self, status, value):
        data = canonical_json(value).encode('utf-8')
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def log_message(self, format, *args):
        return


def make_server(database, port, open_store, handler):
    with closing(open_store(database)):
        server = ThreadingHTTPServer(('127.0.0.1', port), handler)
    server.database = database
    return server


def serve(service_name, server_factory, argv=None):
    parser = argparse.ArgumentParser(description=service_name)
    parser.add_argument('--db', required=True, help='SQLite database path')
    parser.add_argument('--port', type=int, default=0, help='Loopback HTTP port')
    args = parser.parse_args(argv)
    with server_factory(args.db, args.port) as server:
        host, port = server.server_address
        print(canonical_json({'host': host, 'port': port}), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return
