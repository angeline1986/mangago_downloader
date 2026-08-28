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
from src.models import Manga, SearchResult, Chapter, DownloadResult
from gui.config import ConfigManager
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
        with tempfile.TemporaryDirectory() as tmp:
            manager = ConfigManager(config_file=str(Path(tmp) / 'gui_config.json'))
            defaults = manager.default_config
        self.assertEqual(float(defaults.get('page_delay', 2.0)), 2.0)
        self.assertFalse(defaults.get('auto_generate_pdf', False))

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

    def test_auto_generate_pdf_false_does_not_generate_after_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp) / 'Demo' / 'Ch. 1'
            chapter_dir.mkdir(parents=True)
            Path(chapter_dir, 'page-001.jpg').write_bytes(b'image')
            manga = Manga(title='Demo', url='https://example.test/manga')
            chapter = Chapter(number=1.0, url='https://example.test/ch1')
            job_id, _ = self.make_completed_job(chapter_dir, chapter.url)
            with patch.object(server, 'discover_chapter_reader_pages_with_cookies', return_value=(['https://example.test/pg-1'], '')):
                with patch.object(server.ChapterDownloader, 'download_chapters') as download_chapters:
                    download_chapters.side_effect = lambda manga_arg, chapters_arg, result_callback: result_callback(
                        DownloadResult(chapter=chapter, success=True, file_path=str(chapter_dir), images_downloaded=1)
                    )
                    with patch.object(server, 'convert_to_pdf') as convert:
                        server._run_download(job_id, manga, [chapter], {'download_location': tmp, 'auto_generate_pdf': False})
            convert.assert_not_called()

    def test_auto_generate_pdf_true_generates_after_chapter_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp) / 'Demo' / 'Ch. 1'
            chapter_dir.mkdir(parents=True)
            Path(chapter_dir, 'page-001.jpg').write_bytes(b'image')
            manga = Manga(title='Demo', url='https://example.test/manga')
            chapter = Chapter(number=1.0, url='https://example.test/ch1')
            job_id, _ = self.make_completed_job(chapter_dir, chapter.url)
            with patch.object(server, 'discover_chapter_reader_pages_with_cookies', return_value=(['https://example.test/pg-1'], '')):
                with patch.object(server.ChapterDownloader, 'download_chapters') as download_chapters:
                    download_chapters.side_effect = lambda manga_arg, chapters_arg, result_callback: result_callback(
                        DownloadResult(chapter=chapter, success=True, file_path=str(chapter_dir), images_downloaded=1)
                    )
                    with patch.object(server, 'convert_to_pdf', return_value=str(chapter_dir / 'Ch. 1.pdf')) as convert:
                        server._run_download(job_id, manga, [chapter], {'download_location': tmp, 'auto_generate_pdf': True})
            convert.assert_called_once()
            with server._jobs_lock:
                row = server._jobs[job_id]['chapters'][0]
            self.assertEqual(row['status'], 'completed')
            self.assertEqual(row['pdf_status'], 'generated')

    def test_auto_generate_pdf_waits_for_download_result_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp) / 'Demo' / 'Ch. 1'
            chapter_dir.mkdir(parents=True)
            Path(chapter_dir, 'page-001.jpg').write_bytes(b'image')
            manga = Manga(title='Demo', url='https://example.test/manga')
            chapter = Chapter(number=1.0, url='https://example.test/ch1')
            job_id, _ = self.make_completed_job(chapter_dir, chapter.url)
            with patch.object(server, 'discover_chapter_reader_pages_with_cookies', return_value=(['https://example.test/pg-1'], '')):
                with patch.object(server.ChapterDownloader, 'download_chapters') as download_chapters:
                    with patch.object(server, 'convert_to_pdf', return_value=str(chapter_dir / 'Ch. 1.pdf')) as convert:
                        def finish_later(manga_arg, chapters_arg, result_callback):
                            convert.assert_not_called()
                            result_callback(DownloadResult(chapter=chapter, success=True, file_path=str(chapter_dir), images_downloaded=1))
                        download_chapters.side_effect = finish_later
                        server._run_download(job_id, manga, [chapter], {'download_location': tmp, 'auto_generate_pdf': True})
            convert.assert_called_once()

    def test_auto_generate_pdf_does_not_regenerate_existing_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp) / 'Demo' / 'Ch. 1'
            chapter_dir.mkdir(parents=True)
            Path(chapter_dir, 'page-001.jpg').write_bytes(b'image')
            Path(chapter_dir, 'Ch. 1.pdf').write_bytes(b'%PDF')
            manga = Manga(title='Demo', url='https://example.test/manga')
            chapter = Chapter(number=1.0, url='https://example.test/ch1')
            job_id, _ = self.make_completed_job(chapter_dir, chapter.url)
            with patch.object(server, 'discover_chapter_reader_pages_with_cookies', return_value=(['https://example.test/pg-1'], '')):
                with patch.object(server.ChapterDownloader, 'download_chapters') as download_chapters:
                    download_chapters.side_effect = lambda manga_arg, chapters_arg, result_callback: result_callback(
                        DownloadResult(chapter=chapter, success=True, file_path=str(chapter_dir), images_downloaded=1)
                    )
                    with patch.object(server, 'convert_to_pdf') as convert:
                        server._run_download(job_id, manga, [chapter], {'download_location': tmp, 'auto_generate_pdf': True})
            convert.assert_not_called()
            with server._jobs_lock:
                row = server._jobs[job_id]['chapters'][0]
            self.assertEqual(row['pdf_status'], 'existing')

    def test_auto_generate_pdf_failure_is_recorded_without_failing_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp) / 'Demo' / 'Ch. 1'
            chapter_dir.mkdir(parents=True)
            Path(chapter_dir, 'page-001.jpg').write_bytes(b'image')
            manga = Manga(title='Demo', url='https://example.test/manga')
            chapter = Chapter(number=1.0, url='https://example.test/ch1')
            job_id, _ = self.make_completed_job(chapter_dir, chapter.url)
            with patch.object(server, 'discover_chapter_reader_pages_with_cookies', return_value=(['https://example.test/pg-1'], '')):
                with patch.object(server.ChapterDownloader, 'download_chapters') as download_chapters:
                    download_chapters.side_effect = lambda manga_arg, chapters_arg, result_callback: result_callback(
                        DownloadResult(chapter=chapter, success=True, file_path=str(chapter_dir), images_downloaded=1)
                    )
                    with patch.object(server, 'convert_to_pdf', side_effect=RuntimeError('boom')):
                        server._run_download(job_id, manga, [chapter], {'download_location': tmp, 'auto_generate_pdf': True})
            with server._jobs_lock:
                row = server._jobs[job_id]['chapters'][0]
                job = server._jobs[job_id]
            self.assertEqual(row['status'], 'completed')
            self.assertEqual(row['pdf_status'], 'failed')
            self.assertIn('boom', row['pdf_error'])
            self.assertEqual(job['failed'], 0)

    def test_auto_generate_pdf_processes_two_completed_chapters_independently(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chapter_dirs = [root / 'Demo' / 'Ch. 1', root / 'Demo' / 'Ch. 2']
            for chapter_dir in chapter_dirs:
                chapter_dir.mkdir(parents=True)
                Path(chapter_dir, 'page-001.jpg').write_bytes(b'image')
            manga = Manga(title='Demo', url='https://example.test/manga')
            chapters = [
                Chapter(number=1.0, url='https://example.test/ch1'),
                Chapter(number=2.0, url='https://example.test/ch2'),
            ]
            job_id = 'jobpdf-two'
            with server._jobs_lock:
                server._jobs[job_id] = {
                    'id': job_id,
                    'state': 'queued',
                    'phase': 'queued',
                    'message': 'Na fila',
                    'manga': {'title': 'Demo'},
                    'total': 2,
                    'completed': 0,
                    'failed': 0,
                    'progress': 0,
                    'active_count': 0,
                    'created_at': 1,
                    'finished_at': None,
                    'download_root': str(root.resolve()),
                    'chapters': [
                        {'number': 1.0, 'title': 'Ch.1', 'url': chapters[0].url, 'status': 'queued', 'progress': 0, 'current_page': 0, 'total_pages': 0, 'images_downloaded': 0, 'file_path': '', 'message': 'Aguardando', 'pdf_status': 'pending', 'pdf_error': '', 'pdf_message': ''},
                        {'number': 2.0, 'title': 'Ch.2', 'url': chapters[1].url, 'status': 'queued', 'progress': 0, 'current_page': 0, 'total_pages': 0, 'images_downloaded': 0, 'file_path': '', 'message': 'Aguardando', 'pdf_status': 'pending', 'pdf_error': '', 'pdf_message': ''},
                    ],
                }

            def finish_both(manga_arg, chapters_arg, result_callback):
                self.assertEqual([chapter.url for chapter in chapters_arg], [chapters[0].url, chapters[1].url])
                result_callback(DownloadResult(chapter=chapters[0], success=True, file_path=str(chapter_dirs[0]), images_downloaded=1))
                result_callback(DownloadResult(chapter=chapters[1], success=True, file_path=str(chapter_dirs[1]), images_downloaded=1))

            with patch.object(server, 'discover_chapter_reader_pages_with_cookies', side_effect=[(['https://example.test/pg-1'], ''), (['https://example.test/pg-1'], '')]):
                with patch.object(server.ChapterDownloader, 'download_chapters', side_effect=finish_both):
                    with patch.object(server, 'convert_to_pdf', side_effect=[RuntimeError('pdf one failed'), str(chapter_dirs[1] / 'Ch. 2.pdf')]) as convert:
                        server._run_download(job_id, manga, chapters, {'download_location': str(root), 'auto_generate_pdf': True})

            self.assertEqual(convert.call_count, 2)
            self.assertEqual(convert.call_args_list[0].args[0], str(chapter_dirs[0].resolve()))
            self.assertEqual(convert.call_args_list[1].args[0], str(chapter_dirs[1].resolve()))
            self.assertNotEqual(Path(convert.call_args_list[0].kwargs['output_path']).parent, Path(convert.call_args_list[1].kwargs['output_path']).parent)
            with server._jobs_lock:
                rows = server._jobs[job_id]['chapters']
                job = server._jobs[job_id]
            self.assertEqual(rows[0]['status'], 'completed')
            self.assertEqual(rows[0]['pdf_status'], 'failed')
            self.assertIn('pdf one failed', rows[0]['pdf_error'])
            self.assertEqual(rows[1]['status'], 'completed')
            self.assertEqual(rows[1]['pdf_status'], 'generated')
            self.assertEqual(job['failed'], 0)

    def test_auto_generate_pdf_generates_both_pdfs_for_two_chapter_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chapter_dirs = [root / 'Demo' / 'Ch. 1', root / 'Demo' / 'Ch. 2']
            for chapter_dir in chapter_dirs:
                chapter_dir.mkdir(parents=True)
                Path(chapter_dir, 'page-001.jpg').write_bytes(b'image')
            manga = Manga(title='Demo', url='https://example.test/manga')
            chapters = [
                Chapter(number=1.0, url='https://example.test/ch1'),
                Chapter(number=2.0, url='https://example.test/ch2'),
            ]
            job_id = 'jobpdf-two-ok'
            with server._jobs_lock:
                server._jobs[job_id] = {
                    'id': job_id,
                    'state': 'queued',
                    'phase': 'queued',
                    'message': 'Na fila',
                    'manga': {'title': 'Demo'},
                    'total': 2,
                    'completed': 0,
                    'failed': 0,
                    'progress': 0,
                    'active_count': 0,
                    'created_at': 1,
                    'finished_at': None,
                    'download_root': str(root.resolve()),
                    'chapters': [
                        {'number': 1.0, 'title': 'Ch.1', 'url': chapters[0].url, 'status': 'queued', 'progress': 0, 'current_page': 0, 'total_pages': 0, 'images_downloaded': 0, 'file_path': '', 'message': 'Aguardando', 'pdf_status': 'pending', 'pdf_error': '', 'pdf_message': ''},
                        {'number': 2.0, 'title': 'Ch.2', 'url': chapters[1].url, 'status': 'queued', 'progress': 0, 'current_page': 0, 'total_pages': 0, 'images_downloaded': 0, 'file_path': '', 'message': 'Aguardando', 'pdf_status': 'pending', 'pdf_error': '', 'pdf_message': ''},
                    ],
                }

            def finish_both(manga_arg, chapters_arg, result_callback):
                result_callback(DownloadResult(chapter=chapters[0], success=True, file_path=str(chapter_dirs[0]), images_downloaded=1))
                result_callback(DownloadResult(chapter=chapters[1], success=True, file_path=str(chapter_dirs[1]), images_downloaded=1))

            with patch.object(server, 'discover_chapter_reader_pages_with_cookies', side_effect=[(['https://example.test/pg-1'], ''), (['https://example.test/pg-1'], '')]):
                with patch.object(server.ChapterDownloader, 'download_chapters', side_effect=finish_both):
                    with patch.object(server, 'convert_to_pdf', side_effect=[str(chapter_dirs[0] / 'Ch. 1.pdf'), str(chapter_dirs[1] / 'Ch. 2.pdf')]) as convert:
                        server._run_download(job_id, manga, chapters, {'download_location': str(root), 'auto_generate_pdf': True})

            self.assertEqual(convert.call_count, 2)
            self.assertEqual(convert.call_args_list[0].args[0], str(chapter_dirs[0].resolve()))
            self.assertEqual(convert.call_args_list[1].args[0], str(chapter_dirs[1].resolve()))
            with server._jobs_lock:
                rows = server._jobs[job_id]['chapters']
            self.assertEqual(rows[0]['pdf_status'], 'generated')
            self.assertEqual(rows[1]['pdf_status'], 'generated')
            self.assertNotEqual(Path(rows[0]['pdf_path']).parent, Path(rows[1]['pdf_path']).parent)


if __name__ == '__main__':
    unittest.main()
