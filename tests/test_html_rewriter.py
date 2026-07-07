from app.html_rewriter import (
    extract_head_meta,
    html_to_markdown,
    make_links_absolute,
    strip_data_url_images,
    strip_inline_scripts,
    strip_inline_styles,
    strip_large_styles,
)


class TestStripDataUrlImages:
    def test_replaces_inline_base64_image_with_sentinel(self):
        long_blob = "iVBORw0KGgoAAAANSUhEUgAAAA" + "A" * 5000
        html = f'<img src="data:image/png;base64,{long_blob}" alt="hi">'
        out = strip_data_url_images(html)
        assert "STRIPPED" in out
        assert long_blob not in out
        assert "<img" in out
        assert 'alt="hi"' in out

    def test_handles_svg_xml_base64(self):
        html = '<img src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4=">'
        out = strip_data_url_images(html)
        assert "data:image/png;base64,STRIPPED" in out
        assert "PHN2ZyB4bWxucz" not in out

    def test_strips_every_blob_on_a_page(self):
        html = (
            '<img src="data:image/png;base64,AAAA">'
            '<img src="data:image/jpeg;base64,BBBB">'
            '<img src="data:image/webp;base64,CCCC">'
        )
        out = strip_data_url_images(html)
        assert out.count("STRIPPED") == 3
        for marker in ("AAAA", "BBBB", "CCCC"):
            assert marker not in out

    def test_leaves_non_data_image_urls_intact(self):
        html = '<img src="https://example.com/img.png"><img src="/local.jpg">'
        assert strip_data_url_images(html) == html

    def test_leaves_non_image_data_urls_intact(self):
        # Font / CSS / text data URLs are not in scope
        html = "<style>@font-face { src: url(data:font/woff2;base64,AAAAAA); }</style>"
        assert strip_data_url_images(html) == html


class TestExtractHeadMeta:
    def test_extracts_title(self):
        html = "<html><head><title>My Page</title></head><body></body></html>"
        result = extract_head_meta(html)
        assert result["title"] == "My Page"

    def test_extracts_meta_tags(self):
        html = '<html><head><meta name="description" content="A test"><meta property="og:title" content="OG"></head></html>'
        result = extract_head_meta(html)
        assert result["description"] == "A test"
        assert result["og:title"] == "OG"

    def test_extracts_canonical(self):
        html = '<html><head><link rel="canonical" href="https://example.com/page"></head></html>'
        result = extract_head_meta(html)
        assert result["canonical"] == "https://example.com/page"

    def test_filters_non_allowed_keys(self):
        html = (
            '<html><head><meta name="random-key" content="value"><meta name="description" content="ok"></head></html>'
        )
        result = extract_head_meta(html)
        assert "random-key" not in result
        assert result["description"] == "ok"

    def test_empty_html(self):
        assert extract_head_meta("") == {}

    def test_no_head(self):
        result = extract_head_meta("<html><body><p>Hello</p></body></html>")
        assert result == {}

    def test_truncates_long_values(self):
        long_value = "x" * 500
        html = f'<html><head><meta name="description" content="{long_value}"></head></html>'
        result = extract_head_meta(html)
        assert "description" not in result


class TestStripInlineScripts:
    def test_removes_inline_scripts(self):
        html = '<html><head><script>alert("hi")</script></head><body><p>Hello</p></body></html>'
        result = strip_inline_scripts(html)
        assert "alert" not in result
        assert "<p>Hello</p>" in result

    def test_keeps_external_scripts(self):
        html = '<html><head><script src="/app.js"></script></head><body></body></html>'
        result = strip_inline_scripts(html)
        assert 'src="/app.js"' in result


class TestMakeLinksAbsolute:
    def test_resolves_relative_href(self):
        html = '<a href="/page">Link</a>'
        result = make_links_absolute(html, "https://example.com/")
        assert 'href="https://example.com/page"' in result

    def test_keeps_absolute_urls(self):
        html = '<a href="https://other.com/page">Link</a>'
        result = make_links_absolute(html, "https://example.com/")
        assert 'href="https://other.com/page"' in result

    def test_resolves_relative_src(self):
        html = '<img src="/img/photo.jpg">'
        result = make_links_absolute(html, "https://example.com/")
        assert 'src="https://example.com/img/photo.jpg"' in result


class TestHtmlToMarkdown:
    def test_converts_simple_html(self):
        html = "<h1>Hello</h1><p>World</p>"
        result = html_to_markdown(html)
        assert result is not None
        assert "Hello" in result
        assert "World" in result

    def test_returns_none_for_oversized(self):
        html = "x" * 6_000_000
        result = html_to_markdown(html)
        assert result is None

    def test_handles_empty_string(self):
        result = html_to_markdown("")
        # Empty string may return None or empty string
        assert result is None or result == ""


class TestStripLargeStyles:
    def test_removes_large_style_blocks(self):
        large_css = "x" * 3000
        html = f"<style>{large_css}</style><p>Hello</p>"
        result = strip_large_styles(html)
        assert "<style>" not in result
        assert "<p>Hello</p>" in result

    def test_keeps_small_style_blocks(self):
        html = "<style>body { color: red; }</style><p>Hello</p>"
        result = strip_large_styles(html)
        assert "<style>" in result


class TestStripInlineStyles:
    def test_removes_style_attributes(self):
        html = '<p style="color: red;">Hello</p>'
        result = strip_inline_styles(html)
        assert "style" not in result
        assert "<p>Hello</p>" in result
