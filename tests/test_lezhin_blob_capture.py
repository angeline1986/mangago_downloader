import base64
import io
from PIL import Image
from src.lezhin.reader import read_blob_cut_png
from src.lezhin.persistence import persist_cut
from src.lezhin.validation import validate_capture
import pytest

class Locator:
    def __init__(self, response): self.response=response
    def evaluate(self, javascript):
        assert 'toBlob' in javascript and 'naturalWidth' in javascript
        return self.response

class Page:
    def __init__(self, response): self.response=response
    def locator(self, selector):
        assert selector == '[data-cut-index="0"]'
        return self
    @property
    def first(self): return Locator(self.response)

def test_blob_png_is_persisted_with_dimensions_and_validated(tmp_path):
    stream=io.BytesIO()
    Image.new('RGB', (13,17), 'blue').save(stream,'PNG')
    data=read_blob_cut_png(Page({'data':base64.b64encode(stream.getvalue()).decode()}),0)
    cut=persist_cut(tmp_path,0,data,'image/png')
    assert (cut.width,cut.height)==(13,17)
    assert validate_capture(tmp_path,(0,)).valid
    assert not validate_capture(tmp_path,(0,1)).valid

def test_invalid_blob_data_rejected():
    with pytest.raises(Exception, match='Invalid blob PNG'):
        read_blob_cut_png(Page({'data':'not-valid-base64!'}),0)
