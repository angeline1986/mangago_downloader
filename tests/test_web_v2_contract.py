import http.client
import sys
import types
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

if 'img2pdf' not in sys.modules:
    stub = types.ModuleType('img2pdf')
    stub.convert = lambda *args, **kwargs: b''
    sys.modules['img2pdf'] = stub

from src.converter import _get_image_files
from src.models import Manga, SearchResult, Chapter
from webapp import server


class WebV2ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.create_server('127.0.0.1', 0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def request(self, method, path, body=None):
        import json
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        headers = {'Content-Type': 'application/json'}
        conn.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=headers)
        response = conn.getresponse()
        raw = response.read()
        ctype = response.getheader('Content-Type') or ''
        conn.close()
        if 'application/json' in ctype:
            return response.status, json.loads(raw.decode())
        return response.status, raw.decode()

    def test_health_and_local_web_shell(self):
        status, data = self.request('GET', '/api/health')
        self.assertEqual(status, 200)
        self.assertTrue(data['ok'])
        status, html = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn('Ajustes de download', html)
        self.assertIn('Capítulos', html)

    def test_search_api_serializes_existing_core_models(self):
        manga = Manga(title='Demo', url='https://example.test/manga', author='Autor')
        with patch.object(server, 'search_manga', return_value=[SearchResult(index=1, manga=manga)]):
            status, data = self.request('GET', '/api/search?q=demo')
        self.assertEqual(status, 200)
        self.assertEqual(data['results'][0]['title'], 'Demo')

    def test_manga_api_returns_details_and_chapters(self):
        manga = Manga(title='Demo', url='https://example.test/manga')
        chapters = [Chapter(number=1.0, url='https://example.test/ch1', title='Ch.1')]
        with patch.object(server, 'get_manga_details', return_value=(manga, manga.url)), patch.object(server, 'get_chapter_list', return_value=chapters):
            status, data = self.request('POST', '/api/manga', {'url': manga.url})
        self.assertEqual(status, 200)
        self.assertEqual(data['manga']['total_chapters'], 1)

    def test_converter_natural_sort_supports_page_filenames(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('page-010.png', 'page-002.png', 'page-001.png'):
                Path(tmp, name).write_bytes(b'x')
            ordered = [Path(p).name for p in _get_image_files(tmp)]
        self.assertEqual(ordered, ['page-001.png', 'page-002.png', 'page-010.png'])

    def test_default_page_delay_remains_two_seconds(self):
        self.assertEqual(float(server._config.get('page_delay', 2.0)), 2.0)


if __name__ == '__main__':
    unittest.main()
