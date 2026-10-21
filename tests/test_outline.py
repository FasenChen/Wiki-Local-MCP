import pytest

from confluence_mcp.outline import extract_section, find_headings


def test_find_headings_returns_level_title_and_anchor():
    storage = '<h1>Guide</h1><h2>Overview</h2><p>x</p><h3 id="raw">Details &amp; Notes</h3>'

    headings = find_headings(storage)

    assert [(h.level, h.title, h.anchor) for h in headings] == [
        (1, "Guide", "guide"),
        (2, "Overview", "overview"),
        (3, "Details & Notes", "details-notes"),
    ]


def test_find_headings_ignores_headings_inside_cdata_and_comments():
    storage = (
        '<ac:plain-text-body><![CDATA[<h2>Fake</h2>]]></ac:plain-text-body>'
        '<!-- <h2>Commented</h2> --><h2>Real</h2>'
    )

    assert [h.title for h in find_headings(storage)] == ["Real"]


def test_extract_section_stops_at_next_same_or_higher_level():
    storage = '<h1>A</h1><p>a</p><h2>B</h2><p>b</p><h2>C</h2><p>c</p><h1>D</h1>'

    heading, body = extract_section(storage, "A")

    assert heading.title == "A"
    assert body == '<p>a</p><h2>B</h2><p>b</p><h2>C</h2><p>c</p>'


def test_extract_section_last_heading_runs_to_end():
    storage = '<h1>A</h1><h2>Last</h2><p>tail</p>'

    _, body = extract_section(storage, "Last")

    assert body == '<p>tail</p>'


def test_extract_section_is_case_insensitive_when_unique():
    storage = '<h2>Notes</h2><p>n</p>'

    assert extract_section(storage, "notes")[0].title == "Notes"


def test_extract_section_rejects_ambiguous_titles():
    storage = '<h2>Notes</h2><p>1</p><h2>notes</h2><p>2</p>'

    with pytest.raises(ValueError, match="more than one"):
        extract_section(storage, "Notes")


def test_extract_section_lists_available_titles_when_missing():
    storage = '<h1>A</h1><h2>B</h2>'

    with pytest.raises(ValueError, match="Available sections: A, B"):
        extract_section(storage, "C")
