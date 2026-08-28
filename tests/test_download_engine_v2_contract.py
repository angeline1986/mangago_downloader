import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class DownloadEngineV2Contract(unittest.TestCase):
    def test_downloader_has_real_runtime_settings(self):
        text=(ROOT/'src/downloader.py').read_text()
        self.assertIn('retry_count: int = 3', text)
        self.assertIn('timeout: int = 30', text)
        self.assertIn('ThreadPoolExecutor(max_workers=self.max_workers)', text)
        self.assertIn('_wait_for_request_slot', text)
        self.assertIn('_get_session', text)
        self.assertIn('timeout=self.timeout', text)

    def test_web_uses_concurrent_core(self):
        text=(ROOT/'webapp/server.py').read_text()
        self.assertIn('downloader.download_chapters(manga, valid_chapters', text)
        self.assertIn('retry_count=int(settings.get("retry_count", 3))', text)
        self.assertIn('timeout=int(settings.get("timeout", 30))', text)
        self.assertIn('min(3, int(settings.get("max_workers", 3)))', text)

    def test_broken_mutation_observer_filter_is_removed(self):
        text=(ROOT/'webapp/static/app.js').read_text()
        self.assertNotIn('MutationObserver', text)
        self.assertNotIn('CHAPTER_TYPE_FILTER_V1', text)
        self.assertIn('visibleChapterIndexes', text)
        self.assertIn('chapterTypeSegment', text)

    def test_original_quality_is_default(self):
        config=json.loads((ROOT/'gui_config.json').read_text())
        self.assertEqual(config['image_format'], 'original')
        self.assertFalse(config['keep_originals'])
        html=(ROOT/'webapp/templates/index.html').read_text()
        self.assertIn('Original — sem perda de qualidade', html)

if __name__=='__main__':
    unittest.main()
