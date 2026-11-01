import json

import pytest

from confluence_mcp import apply, queue, server, writes
from confluence_mcp.client import ConfluenceAPIError, ConfluenceClient, ConfluenceConfigurationError


@pytest.fixture(autouse=True)
def _writes(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.delenv("CONFLUENCE_WRITE_SPACES", raising=False)
    monkeypatch.setattr(writes, "AUDIT_PATH", tmp_path / "audit.log")


def _page(page_id, title, parent=None, space="OPS"):
    ancestors = [{"id": "1", "title": "Root"}]
    if parent:
        ancestors.append({"id": parent, "title": f"P{parent}"})
    return {
        "id": page_id, "title": title, "space": {"key": space},
        "version": {"number": 5}, "ancestors": ancestors,
    }


@pytest.fixture
def tree(fake_client):
    # Parent 10 has children A(11), B(12), C(13); parent 20 has D(21).
    fake_client.pages.update({
        "10": _page("10", "P10"),
        "11": _page("11", "A", "10"),
        "12": _page("12", "B", "10"),
        "13": _page("13", "C", "10"),
        "20": _page("20", "P20"),
        "21": _page("21", "D", "20"),
    })
    fake_client.children["10"] = [fake_client.pages[i] for i in ("11", "12", "13")]
    fake_client.children["20"] = [fake_client.pages["21"]]
    return fake_client


def test_dry_run_shows_order_before_and_after(tree):
    result = server.move_page("13", "before", "11")
    assert result["dry_run"] is True
    assert result["order_before"] == ["A", "B", "C"]
    assert result["order_after"] == ["C", "A", "B"]
    assert result["new_parent_page_id"] == "10"
    assert tree.moved == [] and queue.list_ops() == []


def test_after_places_page_behind_target(tree):
    assert server.move_page("11", "after", "12")["order_after"] == ["B", "A", "C"]


def test_append_reparents_as_last_child(tree):
    result = server.move_page("11", "append", "20")
    assert result["old_parent_page_id"] == "10" and result["new_parent_page_id"] == "20"
    assert result["order_after"] == ["D", "A"]


def test_queued_move_is_sent_on_approval(tree):
    queued = server.move_page("13", "before", "11", dry_run=False)
    assert queued["queued"] is True and tree.moved == []
    op = queue.get_op(queued["operation_id"])
    assert op["action"] == "move_page" and op["page_id"] == "13"
    assert op["payload"] == {"title": "C", "position": "before", "target_id": "11"}
    assert "→ 1. C (13)" in op["preview"]

    out = apply.approve_and_apply(tree, [queued["operation_id"]])
    assert tree.moved == [("13", "before", "11")]
    assert tree.updated == [] and tree.created == []
    assert out["executed"][0]["status"] == "succeeded"
    assert out["executed"][0]["result"] == {"id": "13", "version": None, "url": None}
    audit = json.loads(writes.AUDIT_PATH.read_text(encoding="utf-8"))
    assert audit["action"] == "move_page" and audit["result"] == "moved"


def test_rejects_no_op_move(tree):
    with pytest.raises(ValueError, match="already in that position"):
        server.move_page("12", "after", "11")


def test_rejects_moving_under_own_descendant(tree):
    tree.pages["11"]["ancestors"] = [{"id": "1"}, {"id": "10"}]
    with pytest.raises(ValueError, match="descendants"):
        server.move_page("10", "append", "11")


def test_rejects_other_space(tree):
    tree.pages["30"] = _page("30", "Q", space="QA")
    with pytest.raises(ValueError, match="between spaces"):
        server.move_page("11", "append", "30")


def test_rejects_space_root_target(tree):
    tree.pages["1"] = {"id": "1", "title": "Root", "space": {"key": "OPS"}, "ancestors": []}
    with pytest.raises(ValueError, match="space root"):
        server.move_page("10", "before", "1")


@pytest.mark.parametrize("position, target", [("first", "11"), ("before", "abc"), ("before", "13")])
def test_rejects_bad_arguments(tree, position, target):
    with pytest.raises(ValueError):
        server.move_page("13", position, target)


def test_respects_space_whitelist(tree, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_WRITE_SPACES", "QA")
    with pytest.raises(ConfluenceConfigurationError):
        server.move_page("13", "before", "11")


class _Answer:
    """Shape of a real movepage.action answer: completion is nested under progressMeter."""

    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {
            "valid": True, "authorized": True,
            "progressMeter": {"completedSuccessfully": True, "total": 0, "percentageComplete": 0},
            "validationErrors": [],
            "page": {"id": "13", "title": "C"},
        }

    def json(self):
        if not isinstance(self._body, dict):
            raise ValueError("not json")
        return self._body


class _RecordingHttp:
    def __init__(self, answer):
        self.calls = []
        self.answer = answer

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.answer


def _client(answer):
    client = ConfluenceClient.__new__(ConfluenceClient)
    client._base_url = "https://wiki.example.com"
    client._client = _RecordingHttp(answer)
    return client


def test_client_move_posts_the_move_dialog_form():
    client = _client(_Answer())
    client.move_page("13", "before", "11")
    method, url, kwargs = client._client.calls[0]
    assert (method, url) == ("POST", "https://wiki.example.com/pages/movepage.action")
    assert kwargs["data"] == {"pageId": "13", "position": "above", "targetId": "11", "mode": "LEGACY"}
    assert kwargs["headers"] == {"X-Atlassian-Token": "no-check"}


def test_client_move_maps_after_and_append_to_dialog_positions():
    client = _client(_Answer())
    client.move_page("13", "after", "11")
    client.move_page("13", "append", "11")
    assert [c[2]["data"]["position"] for c in client._client.calls] == ["below", "append"]


def test_client_move_rejected_answer_is_an_error_not_success():
    client = _client(_Answer(body={"valid": True, "authorized": True,
                                   "progressMeter": {"completedSuccessfully": False},
                                   "validationErrors": ["no such page"]}))
    with pytest.raises(ConfluenceAPIError, match="refused") as excinfo:
        client.move_page("13", "before", "11")
    assert excinfo.value.status_code == 200


def test_client_move_without_completion_flag_is_not_success():
    client = _client(_Answer(body={"authorized": True, "validationErrors": []}))
    with pytest.raises(ConfluenceAPIError, match="refused"):
        client.move_page("13", "before", "11")


def test_client_move_unauthorized_answer_is_a_failure():
    client = _client(_Answer(body={"authorized": False, "progressMeter": {"completedSuccessfully": False},
                                   "validationErrors": []}))
    with pytest.raises(ConfluenceAPIError, match="authorize") as excinfo:
        client.move_page("13", "before", "11")
    assert excinfo.value.status_code == 401


def test_client_move_http_error_carries_status():
    client = _client(_Answer(status_code=404, body={}))
    with pytest.raises(ConfluenceAPIError) as excinfo:
        client.move_page("13", "before", "11")
    assert excinfo.value.status_code == 404


def test_client_move_rejects_unknown_position():
    client = _client(_Answer())
    with pytest.raises(ValueError):
        client.move_page("13", "first", "11")
    assert client._client.calls == []
