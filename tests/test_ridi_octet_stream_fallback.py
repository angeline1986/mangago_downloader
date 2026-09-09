import unittest

from src.ridi_provider import _RIDI_BLOB_CAPTURE_INIT_SCRIPT


class RidiOctetStreamFallbackContractTests(unittest.TestCase):
    def test_original_image_flow_remains_unchanged(self):
        script = _RIDI_BLOB_CAPTURE_INIT_SCRIPT
        self.assertIn("value.type.startsWith('image/')", script)
        self.assertIn("}).catch(() => {});", script)

    def test_octet_stream_is_separate_fallback(self):
        script = _RIDI_BLOB_CAPTURE_INIT_SCRIPT
        self.assertIn("} else if (", script)
        self.assertIn("value.type === 'application/octet-stream'", script)
        self.assertIn("bytes[0] === 0xFF", script)
        self.assertIn("bytes[1] === 0xD8", script)
        self.assertIn("bytes[2] === 0xFF", script)
        self.assertIn("return 'image/jpeg';", script)
        self.assertIn("record.mimeType = detectedMime;", script)


if __name__ == "__main__":
    unittest.main()
