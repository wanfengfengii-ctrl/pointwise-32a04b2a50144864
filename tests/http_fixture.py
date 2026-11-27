from contextlib import contextmanager
from http.client import HTTPConnection
import json
from threading import Event, Lock, Thread
from urllib.parse import urlencode, urlsplit


HTTP_TIMEOUT = 12


class HttpClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port

    def request(self, method, path, *, body=None, query=None):
        if query is not None:
            path = f'{path}?{urlencode(query)}'
        data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
        headers = {'Content-Type': 'application/json'} if data is not None else {}
        connection = HTTPConnection(self.host, self.port, timeout=HTTP_TIMEOUT)
        try:
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def ok(self, method, path, *, body=None, query=None):
        status, value = self.request(method, path, body=body, query=query)
        if status != 200:
            raise AssertionError(f'{method} {path} returned {status}: {value}')
        return value


class RequestGate:
    def __init__(self, method, path, phase, drop):
        self.key = (method, path, phase)
        self.drop = drop
        self.entered = Event()
        self.released = Event()

    def hold(self, handler):
        self.entered.set()
        if not self.released.wait(HTTP_TIMEOUT):
            raise AssertionError(f'HTTP gate timed out: {self.key}')
        if self.drop:
            handler.close_connection = True
        return self.drop

    def wait_until_held(self):
        if not self.entered.wait(HTTP_TIMEOUT):
            raise AssertionError(f'HTTP gate was not reached: {self.key}')

    def release(self):
        self.released.set()


class LoopbackService:
    def __init__(self, factory, database):
        self.factory = factory
        self.database = database
        self.server = None
        self.thread = None
        self.client = None
        self._gate = None
        self._lock = Lock()

    def start(self):
        if self.server is not None:
            raise RuntimeError('service is already running')
        self.server = self.factory(self.database)
        original_handler = self.server.RequestHandlerClass
        service = self

        class GatedHandler(original_handler):
            def dispatch(self, method):
                gate = service._take_gate(self, 'before')
                if gate is None or not gate.hold(self):
                    super().dispatch(method)

            def write_result(self, status, value):
                gate = service._take_gate(self, 'after') if status == 200 else None
                if gate is None or not gate.hold(self):
                    super().write_result(status, value)

        self.server.RequestHandlerClass = GatedHandler
        self.client = HttpClient(*self.server.server_address)
        self.thread = Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join()
            self.server = None
            self.thread = None

    @contextmanager
    def hold(self, method, path, *, phase, drop=False):
        if phase not in {'before', 'after'}:
            raise ValueError('unknown gate phase')
        gate = RequestGate(method, path, phase, drop)
        with self._lock:
            if self._gate is not None:
                raise RuntimeError('an HTTP gate is already armed')
            self._gate = gate
        try:
            yield gate
        finally:
            with self._lock:
                if self._gate is gate:
                    self._gate = None
            gate.release()

    def _take_gate(self, handler, phase):
        key = (handler.command, urlsplit(handler.path).path, phase)
        with self._lock:
            if self._gate is not None and self._gate.key == key:
                gate = self._gate
                self._gate = None
                return gate
        return None
