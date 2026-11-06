import pytest

from confluence_mcp import preview


def _html(storage):
    return preview.storage_to_preview_html(storage)


def test_active_markup_and_unsafe_urls_are_removed():
    out = _html(
        '<p onclick="x()">hi <script>alert(1)</script><iframe src="https://evil.example"></iframe>'
        '<img src="javascript:alert(1)" onerror="x()"><a href="javascript:alert(2)">go</a></p>'
    )
    for banned in ("<script", "<iframe", "onclick", "onerror", "javascript:"):
        assert banned not in out
    assert out.startswith("<p>hi ") and ">go<" in out


def test_text_is_escaped_not_interpreted():
    assert _html("<p>a &lt;b&gt; &amp; &quot;c&quot;</p>") == "<p>a &lt;b&gt; &amp; &quot;c&quot;</p>"


def test_code_macro_keeps_cdata_literal_and_shows_language():
    out = _html(
        '<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">python</ac:parameter>'
        '<ac:plain-text-body><![CDATA[if a < b: print("<script>")]]></ac:plain-text-body>'
        "</ac:structured-macro>"
    )
    assert "<pre><code>if a &lt; b: print(&quot;&lt;script&gt;&quot;)" in out
    assert "代码 · python" in out and "<script" not in out


def test_unsupported_macro_is_labelled_and_not_shown_as_rendered():
    out = _html('<ac:structured-macro ac:name="jira"><ac:rich-text-body><p>body</p></ac:rich-text-body></ac:structured-macro>')
    assert "宏未渲染：jira" in out and "<p>body</p>" in out


def test_external_images_render_and_attachments_are_labelled():
    out = _html(
        '<img src="https://img.example/a.png" alt="A">'
        '<ac:image><ri:url ri:value="https://img.example/b.png"/></ac:image>'
        '<ac:image><ri:attachment ri:filename="diagram.png"/></ac:image>'
    )
    assert '<img src="https://img.example/a.png" alt="A" referrerpolicy="no-referrer">' in out
    assert '<img src="https://img.example/b.png"' in out
    assert "附件 diagram.png" in out and out.count("<img ") == 2


def test_tables_lists_and_spans_survive():
    out = _html(
        '<table><tbody><tr><th>a</th><td colspan="2" onclick="x">b</td></tr></tbody></table>'
        "<ul><li>x</li></ul>"
    )
    assert '<td colspan="2">b</td>' in out and "<ul><li>x</li></ul>" in out
    assert "onclick" not in out


def test_deep_nesting_does_not_exhaust_the_stack():
    out = _html("<div>" * 5000 + "deep" + "</div>" * 5000)
    assert "deep" in out


def test_markdown_written_by_this_server_previews_as_headings_table_and_code():
    from confluence_mcp.markdown_storage import markdown_to_storage

    storage = markdown_to_storage("# Title\n\n```python\nx = 1 < 2\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |")
    out = _html(storage)
    assert "<h1>Title</h1>" in out and "<table>" in out and "<td>2</td>" in out
    assert "x = 1 &lt; 2" in out and "代码 · python" in out


def test_ac_image_keeps_its_alt_text_on_the_paired_ri_url_shape():
    out = _html(
        '<ac:image ac:alt="Architecture diagram" ac:width="300">'
        '<ri:url ri:value="https://img.example/arch.png"></ri:url></ac:image>'
    )
    assert 'alt="Architecture diagram"' in out
    assert '<img src="https://img.example/arch.png"' in out


def test_snapshot_svg_stays_in_an_image_and_arbitrary_data_urls_remain_blocked():
    from confluence_mcp.images import ImageAttachment

    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    image = ImageAttachment("test.svg", "https://images.example/test.svg", "image/svg+xml", svg)
    out = preview.render_document(
        '<ac:image><ri:attachment ri:filename="test.svg"/></ac:image>'
        '<img src="data:text/html,unsafe"/>', [image],
    )
    assert "data:image/svg+xml;base64," in out
    assert "<script" not in out and "data:text/html" not in out


def test_code_cdata_split_across_sections_is_reassembled():
    # markdown_storage splits a literal "]]>" as "]]]]><![CDATA[>"; the body must read back intact.
    out = _html(
        '<ac:structured-macro ac:name="code"><ac:plain-text-body>'
        "<![CDATA[print('a]]]]><![CDATA[>b')]]></ac:plain-text-body></ac:structured-macro>"
    )
    assert "print(&#x27;a]]&gt;b&#x27;)" in out


PROVENANCE_MARKDOWN = (
    "> 原文归档：Android TV Ninja\n"
    "> 来源：[Overview](https://docs.netflixpartners.com/ninja/documentation/overview)\n"
    "> 源文档更新时间：2026-01-01\n\n"
    "# Body\n"
)


def test_provenance_reads_explicit_labels_from_the_leading_blockquote():
    from confluence_mcp.markdown_storage import markdown_to_storage

    info = preview.provenance(markdown_to_storage(PROVENANCE_MARKDOWN))
    assert info == {
        "collection": "Android TV Ninja",
        "source": {
            "label": "Overview",
            "url": "https://docs.netflixpartners.com/ninja/documentation/overview",
            "parent": "https://docs.netflixpartners.com/ninja/documentation",
        },
    }


def test_provenance_accepts_br_separated_lines():
    info = preview.provenance(
        '<blockquote><p>原文归档：X<br />来源：<a href="https://d.example/a/b">B</a></p></blockquote><p>body</p>'
    )
    assert info["collection"] == "X" and info["source"]["url"] == "https://d.example/a/b"


def test_ordinary_links_in_the_body_are_not_provenance():
    assert preview.provenance('<p>来源：<a href="https://evil.example/x">x</a></p>') is None
    assert preview.provenance('<blockquote><p>参考：<a href="https://ref.example/">r</a></p></blockquote>') is None
    assert preview.provenance("<p>plain</p>") is None


def test_label_without_a_valid_link_yields_no_source():
    assert preview.provenance("<blockquote><p>来源：Overview（无链接）</p></blockquote>") is None


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "/relative/path",
        "https://user:secret@docs.example/x",
        "https://docs.example/a b",
        "http://[",
        "http://example.com:bad",
        "https://exa\uff0fmple.test",
    ],
)
def test_malicious_or_odd_source_urls_are_rejected(href):
    storage = f'<blockquote><p>来源：<a href="{href}">Overview</a></p></blockquote>'
    assert preview.provenance(storage) is None


def test_proposed_body_is_the_payload_storage_for_each_kind():
    storage = "<p>new</p>"
    for payload in (
        {"body": {"storage": {"value": storage}}},  # create, comment and page update
        {"body": {"storage": {"value": storage}}, "ancestors": [{"id": "7"}]},
    ):
        assert preview.proposed_storage({"payload": payload, "preview": "-old"}) == storage
    assert preview.proposed_storage({"payload": {"body": "not a dict"}}) == ""
