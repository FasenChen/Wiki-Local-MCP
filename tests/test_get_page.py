import pytest

from confluence_mcp import server

PAGE = {
    "id": "42",
    "title": "Guide",
    "space": {"key": "OPS"},
    "version": {"number": 3},
    "_links": {"webui": "/spaces/OPS/pages/42"},
    "body": {
        "storage": {
            "value": (
                "<h1>Guide</h1><p>intro</p>"
                "<h2>Setup</h2><p>run it</p>"
                "<h2>Notes</h2><p>note</p>"
            )
        }
    },
}


def test_get_page_section_returns_only_that_section(fake_client):
    fake_client.pages["42"] = PAGE

    result = server.get_page("42", section="Setup")

    assert result["content"] == "## Setup\n\nrun it"
    assert result["truncated"] is False


def test_get_page_without_section_returns_full_page(fake_client):
    fake_client.pages["42"] = PAGE

    result = server.get_page("42")

    assert result["content"].startswith("# Guide")
    assert "## Notes" in result["content"]
    assert result["truncated"] is False


def test_get_page_max_chars_truncates_and_flags(fake_client):
    fake_client.pages["42"] = PAGE

    result = server.get_page("42", max_chars=5)

    assert result["content"] == "# Gui"
    assert result["truncated"] is True


def test_get_page_section_rejects_html_output(fake_client):
    fake_client.pages["42"] = PAGE

    with pytest.raises(ValueError, match="output_format"):
        server.get_page("42", output_format="html", section="Setup")


def test_get_page_missing_section_lists_available_titles(fake_client):
    fake_client.pages["42"] = PAGE

    with pytest.raises(ValueError, match="Available sections: Guide, Setup, Notes"):
        server.get_page("42", section="Missing")


def test_get_page_rejects_non_positive_max_chars(fake_client):
    fake_client.pages["42"] = PAGE

    with pytest.raises(ValueError):
        server.get_page("42", max_chars=0)
