import pytest

from pdf2dxf_stable.determinism import canonicalize_ascii_dxf


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
@pytest.mark.parametrize("last_newline", [True, False])
def test_large_opaque_sections_keep_every_nonmetadata_value(tmp_path, newline, last_newline):
    prefix = b"0\nSECTION\n2\nHEADER\n9\n$TDCREATE\n40\n999.5\n0\nENDSEC\n"
    # More than one copy chunk; dates and metadata-looking TEXT remain opaque.
    entities = b"0\nLINE\n5\nA0\n10\n0.123456789012345\n20\n-10.5\n" * 30000
    entities += b"0\nTEXT\n1\nCREATED_BY_EZDXF 999.5 \xe9\n"
    source = prefix + b"0\nSECTION\n2\nENTITIES\n" + entities + b"0\nENDSEC\n0\nEOF\n"
    expected = source.replace(b"40\n999.5\n", b"40\n2451544.5\n", 1).replace(b"\n", b"\r\n")
    source = source.replace(b"\n", newline)
    if not last_newline:
        source = source.rstrip(b"\r\n")
    path = tmp_path / "drawing.dxf"
    path.write_bytes(source)
    canonicalize_ascii_dxf(path, seed="large")
    assert path.read_bytes() == expected


def test_truncated_opaque_entity_is_rejected_atomically(tmp_path):
    path = tmp_path / "truncated.dxf"
    original = b"0\nSECTION\n2\nENTITIES\n0\nLINE\n10\n"
    path.write_bytes(original)
    with pytest.raises(ValueError, match="Truncated"):
        canonicalize_ascii_dxf(path, seed="bad")
    assert path.read_bytes() == original
