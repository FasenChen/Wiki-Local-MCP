from urllib.parse import quote

import httpx
import pytest

from confluence_mcp import images
from confluence_mcp.conversion import storage_to_markdown
from confluence_mcp.markdown_storage import markdown_to_storage


def test_relative_reference_images_are_snapshotted_once(image_file):
    markdown = f'![一][image]\n\n![二][image]\n\n[image]: {quote(image_file.name)} "标题"'
    storage, attachments = images.prepare_images(markdown_to_storage(markdown), str(image_file.parent))
    [image] = attachments
    assert image.data == image_file.read_bytes()
    assert image.source == str(image_file.resolve())
    assert image.content_type == "image/png"
    assert storage.count(f'ri:filename="{image.filename}"') == 2
    assert 'ac:alt="一"' in storage and 'ac:title="标题"' in storage
    assert "<img" not in storage


@pytest.mark.parametrize("as_uri", [False, True])
def test_absolute_paths_and_file_urls_need_no_base_dir(image_file, as_uri):
    source = image_file.as_uri() if as_uri else image_file.as_posix()
    _, [image] = images.prepare_images(markdown_to_storage(f"![图]({source})"))
    assert image.data == image_file.read_bytes()


def test_html_images_preserve_other_storage_and_escape_attributes(image_file):
    storage = f'<h2>保留</h2>\n<p><img width="300" alt="a &amp; &quot;b&quot;" src="{image_file.as_posix()}"></p>'
    result, _ = images.prepare_images(storage)
    assert result.startswith('<h2>保留</h2>\n<p><ac:image')
    assert 'ac:width="300"' in result and 'ac:alt="a &amp; &quot;b&quot;"' in result
    assert result.endswith("</ac:image></p>")


def test_code_examples_and_comments_are_not_images():
    markdown = (
        '```html\n<img src="missing.png">\n```\n\n'
        '`![example](missing.png)`\n\n<!-- <img src="missing.png"> -->'
    )
    original = markdown_to_storage(markdown)
    storage, attachments = images.prepare_images(original)
    assert storage == original and attachments == []


def test_same_content_deduplicates_and_changed_content_gets_a_new_name(image_file):
    copy = image_file.with_name("copy.png")
    copy.write_bytes(image_file.read_bytes())
    _, attachments = images.prepare_images(
        markdown_to_storage(f"![a]({image_file.name}) ![b]({copy.name})"), str(image_file.parent),
    )
    assert len(attachments) == 1
    original_name = attachments[0].filename
    image_file.write_bytes(image_file.read_bytes() + b"changed")
    _, [changed] = images.prepare_images(markdown_to_storage(f"![a]({image_file.as_posix()})"))
    assert changed.filename != original_name


def test_missing_image_and_missing_base_dir_fail_explicitly(tmp_path):
    with pytest.raises(ValueError, match="image_base_dir"):
        images.prepare_images(markdown_to_storage("![a](missing.png)"))
    with pytest.raises(ValueError, match="Could not read image"):
        images.prepare_images(markdown_to_storage("![a](missing.png)"), str(tmp_path))
    with pytest.raises(ValueError, match="existing absolute directory"):
        images.prepare_images("<p>x</p>", "relative")


def test_non_image_file_is_rejected(tmp_path):
    path = tmp_path / ".env"
    path.write_text("example", encoding="utf-8")
    with pytest.raises(ValueError, match="Not a supported image"):
        images.prepare_images(f'<img src="{path.as_posix()}"/>')


def test_network_image_download_uses_no_wiki_client_and_deduplicates(monkeypatch, image_file):
    calls = []

    def download(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, content=image_file.read_bytes(), headers={"Content-Type": "image/png"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(images.httpx, "get", download)
    source = "https://images.example/asset?id=1&size=2"
    storage, [image] = images.prepare_images(markdown_to_storage(f"![a]({source}) ![b]({source})"))
    assert image.source == source and storage.count("ri:attachment") == 2
    assert calls == [(source, {"follow_redirects": True, "timeout": 30.0})]
    assert image.data == image_file.read_bytes()


@pytest.mark.parametrize("status,content_type", [(403, "text/html"), (200, "text/html")])
def test_failed_or_non_image_download_is_rejected(monkeypatch, status, content_type):
    def download(url, **kwargs):
        return httpx.Response(status, content=b"login required", headers={"Content-Type": content_type},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(images.httpx, "get", download)
    with pytest.raises(ValueError):
        images.prepare_images('<img src="https://images.example/image.png"/>')


@pytest.mark.parametrize("src", ["data:image/png;base64,abc", "https://user:secret@images.example/x.png"])
def test_unsupported_or_credentialed_urls_fail_before_downloading(src, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("should not download")

    monkeypatch.setattr(images.httpx, "get", unexpected)
    with pytest.raises(ValueError):
        images.prepare_images(f'<img src="{src}"/>')


def test_attachment_markdown_round_trip_preserves_existing_image_reference():
    storage = '<p><ac:image ac:alt="流程"><ri:attachment ri:filename="流程 图.png" /></ac:image></p>'
    markdown = storage_to_markdown(storage)
    assert "attachment:" in markdown and "流程" in markdown
    result, attachments = images.prepare_images(markdown_to_storage(markdown))
    assert 'ri:filename="流程 图.png"' in result and attachments == []


def test_protocol_relative_image_urls_use_https(monkeypatch, image_file):
    calls = []

    def download(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, content=image_file.read_bytes(), headers={"Content-Type": "image/png"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(images.httpx, "get", download)
    images.prepare_images('<img src="//images.example/a.png"/>')
    assert calls == ["https://images.example/a.png"]


def test_image_replacement_offsets_follow_parser_newlines(image_file):
    prefix = "<p>one\rtwo\u2028three</p>\n"
    storage, _ = images.prepare_images(prefix + f'<img src="{image_file.as_posix()}"/>')
    assert storage.startswith(prefix + "<ac:image>")
