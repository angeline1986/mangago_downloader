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

    def make_completed_job(self, chapter_dir, chapter_url='https://example.test/ch1'):
        job_id = 'jobpdf'
        with server._jobs_lock:
            server._jobs[job_id] = {
                'id': job_id,
                'state': 'completed',
                'phase': 'done',
                'message': 'Download concluído',
                'manga': {'title': 'Demo'},
                'total': 1,
                'completed': 1,
                'failed': 0,
                'progress': 100,
                'active_count': 0,
                'created_at': 1,
                'finished_at': 2,
                'download_root': str(Path(chapter_dir).parents[1]),
                'chapters': [{
                    'number': 1.0,
                    'title': 'Ch.1',
                    'url': chapter_url,
                    'status': 'completed',
                    'progress': 100,
                    'current_page': 1,
                    'total_pages': 1,
                    'images_downloaded': 1,
                    'file_path': str(chapter_dir),
                    'message': 'Concluído',
                }],
            }
        return job_id, chapter_url

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

    def test_pdf_endpoint_generates_pdf_for_completed_chapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp) / 'Demo' / 'Ch. 1'
            chapter_dir.mkdir(parents=True)
            Path(chapter_dir, 'page-001.jpg').write_bytes(b'image')
            job_id, chapter_url = self.make_completed_job(chapter_dir)
            expected_pdf = chapter_dir / 'Ch. 1.pdf'
            with patch.object(server, 'convert_to_pdf', return_value=str(expected_pdf)) as convert:
                status, data = self.request('POST', '/api/pdf', {'job_id': job_id, 'chapter_url': chapter_url})
        self.assertEqual(status, 200)
        self.assertTrue(data['ok'])
        convert.assert_called_once_with(str(chapter_dir.resolve()), output_path=str(expected_pdf.resolve()), delete_images=False)
        with server._jobs_lock:
            row = server._jobs[job_id]['chapters'][0]
        self.assertEqual(row['pdf_status'], 'generated')
        self.assertEqual(row['pdf_message'], 'PDF gerado')

    def test_pdf_endpoint_rejects_empty_chapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp) / 'Demo' / 'Ch. 1'
            chapter_dir.mkdir(parents=True)
            job_id, chapter_url = self.make_completed_job(chapter_dir)
            status, data = self.request('POST', '/api/pdf', {'job_id': job_id, 'chapter_url': chapter_url})
        self.assertEqual(status, 409)
        self.assertIn('Nenhuma imagem', data['error'])

    def test_pdf_endpoint_rejects_unknown_chapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp) / 'Demo' / 'Ch. 1'
            chapter_dir.mkdir(parents=True)
            job_id, _ = self.make_completed_job(chapter_dir)
            status, data = self.request('POST', '/api/pdf', {'job_id': job_id, 'chapter_url': 'https://example.test/missing'})
        self.assertEqual(status, 404)
        self.assertIn('Capítulo não encontrado', data['error'])

    def test_pdf_endpoint_rejects_missing_chapter_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp) / 'Demo' / 'Ch. 1'
            job_id, chapter_url = self.make_completed_job(chapter_dir)
            status, data = self.request('POST', '/api/pdf', {'job_id': job_id, 'chapter_url': chapter_url})
        self.assertEqual(status, 404)
        self.assertIn('não existe', data['error'])

    def test_pdf_endpoint_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            chapter_dir = Path(outside) / 'Ch. 1'
            chapter_dir.mkdir()
            Path(chapter_dir, 'page-001.jpg').write_bytes(b'image')
            job_id, chapter_url = self.make_completed_job(chapter_dir)
            with server._jobs_lock:
                server._jobs[job_id]['download_root'] = str(Path(tmp).resolve())
            status, data = self.request('POST', '/api/pdf', {'job_id': job_id, 'chapter_url': chapter_url})
        self.assertEqual(status, 400)
        self.assertIn('Diretório inválido', data['error'])

    def test_pdf_endpoint_reports_existing_pdf_without_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp) / 'Demo' / 'Ch. 1'
            chapter_dir.mkdir(parents=True)
            Path(chapter_dir, 'page-001.jpg').write_bytes(b'image')
            Path(chapter_dir, 'Ch. 1.pdf').write_bytes(b'%PDF')
            job_id, chapter_url = self.make_completed_job(chapter_dir)
            with patch.object(server, 'convert_to_pdf') as convert:
                status, data = self.request('POST', '/api/pdf', {'job_id': job_id, 'chapter_url': chapter_url})
        self.assertEqual(status, 409)
        self.assertTrue(data['already_exists'])
        convert.assert_not_called()

    def test_download_post_still_creates_job(self):
        manga = {'title': 'Demo', 'url': 'https://example.test/manga'}
        chapters = [{'number': 1.0, 'url': 'https://example.test/ch1', 'title': 'Ch.1'}]
        with patch.object(server, '_run_download') as runner:
            status, data = self.request('POST', '/api/downloads', {'manga': manga, 'chapters': chapters})
        self.assertEqual(status, 202)
        self.assertIn('job_id', data)
        runner.assert_called_once()


if __name__ == '__main__':
    unittest.main()
