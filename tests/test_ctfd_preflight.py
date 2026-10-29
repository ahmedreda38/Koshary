import io
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch
import requests
import preflight_ctfd


class Response:
    status_code = 200
    def raise_for_status(self):
        pass
    def json(self):
        return {"success": True}


class PreflightTests(unittest.TestCase):
    def run_check(self, client, session='session'):
        with tempfile.TemporaryDirectory() as d, \
             patch.object(preflight_ctfd.Path, 'cwd', return_value=Path(d)), \
             patch.object(preflight_ctfd, 'load_json', return_value={'routing': {}, 'ctf': {}}), \
             patch.object(preflight_ctfd, 'CTFdClient', return_value=client), \
             patch.dict('os.environ', {'CTFD_SESSION': session}), \
             patch('sys.argv', ['preflight', '--url', 'http://localhost:18080']), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return preflight_ctfd.main()

    def test_success_and_missing_nonce(self):
        from unittest.mock import Mock
        client = Mock(base_url='http://localhost', nonce='nonce')
        client.s.get.return_value = Response()
        client.get_challenges.return_value = []
        self.assertEqual(self.run_check(client), 0)
        client.nonce = ''
        self.assertEqual(self.run_check(client), 1)

    def test_invalid_session_and_network_failure(self):
        from unittest.mock import Mock
        client = Mock(base_url='http://localhost', nonce='nonce')
        client.s.get.return_value = Response()
        client.s.get.return_value.status_code = 302
        self.assertEqual(self.run_check(client), 1)
        client.s.get.side_effect = requests.ConnectionError()
        self.assertEqual(self.run_check(client), 1)
        self.assertEqual(self.run_check(client, session=''), 1)
