from PIL import Image

from app.pdf_worker import _assemble_raster_pdf, _context_options


def test_assemble_raster_pdf_is_valid_and_lossless():
    images = [Image.new("RGB", (2, 2), color) for color in ("red", "blue")]

    result = _assemble_raster_pdf(images, 200, 100)

    assert result.startswith(b"%PDF-1.4")
    assert b"/Count 2" in result
    assert result.count(b"/FlateDecode") == 2
    assert result.endswith(b"%%EOF\n")


def test_context_options_uses_best_raster_quality_by_default():
    request = {"viewport": {"width": 800, "height": 600}, "page": {"rasterize": True}}

    result = _context_options(request)

    assert result["device_scale_factor"] == 2


def test_context_options_uses_optimized_raster_quality():
    request = {
        "viewport": {"width": 800, "height": 600},
        "page": {"rasterize": True, "raster_quality": "optimized"},
    }

    result = _context_options(request)

    assert result["device_scale_factor"] == 1
