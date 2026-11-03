import ezdxf
import pytest

from pdf2dxf_stable.engine.geometry.base import GenericGraphicsKernelV14
from pdf2dxf_stable.engine.text.outline_text import _source_ref
from pdf2dxf_stable.validation import validate_dxf


@pytest.mark.parametrize("seqno", [32767, 32768, 70000])
def test_large_source_numbers_survive_standard_binary_dxf(tmp_path, seqno):
    doc = ezdxf.new("R2007")
    doc.appids.add("PDF2DXF14")
    entity = doc.modelspace().add_line((0, 0), (1, 1))
    GenericGraphicsKernelV14()._decorate(entity, {}, 0, seqno, "line")
    assert _source_ref(entity, 0) == ("PDF2DXF14", 0, seqno)
    path = tmp_path / "source.dxf"
    doc.saveas(path, fmt="bin")
    restored = ezdxf.readfile(path)
    assert _source_ref(next(iter(restored.modelspace())), 0) == ("PDF2DXF14", 0, seqno)


def test_saved_validator_rejects_out_of_range_xdata_short_integer(tmp_path):
    doc = ezdxf.new("R2007")
    doc.appids.add("SOURCE")
    entity = doc.modelspace().add_line((0, 0), (1, 1))
    entity.set_xdata("SOURCE", [(1070, 70000)])
    path = tmp_path / "invalid.dxf"
    doc.saveas(path)
    result = validate_dxf(path, profile="universal")
    assert not result["valid"]
    assert not result["geometry_valid"]
    assert "XDATA_INTEGER_OUT_OF_RANGE" in {error["code"] for error in result["errors"]}
