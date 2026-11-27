from contextlib import contextmanager
import json
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

from tests.http_fixture import HttpClient
from tests.scenario import issue_sample_pages, load_sample, receipt_input, release_input


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def running_entrypoint(module, database):
    command = [sys.executable, '-B', '-m', module, '--db', str(database), '--port', '0']
    with subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, text=True, encoding='utf-8') as process:
        ready = Queue()
        reader = Thread(target=lambda: ready.put(process.stdout.readline()), daemon=True)
        reader.start()
        try:
            try:
                first_line = ready.get(timeout=12)
            except Empty:
                raise AssertionError(f'{module} produced no startup address') from None
            if not first_line:
                raise AssertionError(f'{module} exited before startup: {process.poll()}')
            address = json.loads(first_line)
            if address['host'] != '127.0.0.1' or not 0 < address['port'] <= 65535:
                raise AssertionError(f'unexpected startup address: {address}')
            yield HttpClient(address['host'], address['port'])
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            reader.join(timeout=5)


class TestRuntime(unittest.TestCase):
    def test_process_entrypoints_keep_independent_stores(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        office_db = directory / 'office.sqlite'
        desk_db = directory / 'desk.sqlite'
        sample = load_sample()
        with running_entrypoint('issue.office_http', office_db) as office:
            draft_release = release_input(office, sample)
            bundle = office.ok('POST', '/release', body=draft_release)
        with running_entrypoint('desk.http', desk_db) as desk:
            installed = desk.ok('POST', '/install', body=bundle)
            receipts = issue_sample_pages(desk, bundle, sample)
        with running_entrypoint('desk.http', desk_db) as desk:
            self.assertEqual(desk.ok('GET', '/install', query={'round_id': 'R'}), installed)
            self.assertEqual(desk.ok('GET', '/receipts', query={'round_id': 'R'})['receipts'], receipts)
        with running_entrypoint('issue.office_http', office_db) as office:
            self.assertEqual(office.ok('POST', '/release', body=draft_release), bundle)
            for receipt in receipts:
                office.ok('POST', '/reconcile', body=receipt_input(bundle, receipt))
            collection = office.ok('POST', '/collection', body={'round_id': 'R'})
            self.assertEqual(collection['pages'], receipts)
        with running_entrypoint('issue.office_http', office_db) as office:
            self.assertEqual(office.ok('GET', '/collection', query={'round_id': 'R'}), collection)
