import pytest


class FakeClient:
    def __init__(self):
        self.pages = {}
        self.search_response = {"results": [], "totalSize": 0}
        self.search_calls = []
        self.spaces_response = {"results": [], "size": 0}

    def get_page(self, page_id):
        return self.pages[page_id]

    def search_pages(self, cql, limit):
        self.search_calls.append((cql, limit, 0))
        return self.search_response.get("results", [])

    def search_cql(self, cql, *, limit, start):
        self.search_calls.append((cql, limit, start))
        return self.search_response

    def list_spaces(self, *, limit, start):
        self.search_calls.append(("spaces", limit, start))
        return self.spaces_response

    def absolute_url(self, path):
        return f"https://wiki.example.com{path}"

    def page_url(self, page):
        return f"https://wiki.example.com/pages/{page['id']}"


@pytest.fixture
def fake_client(monkeypatch):
    from confluence_mcp import server

    client = FakeClient()
    monkeypatch.setattr(server, "get_client", lambda: client)
    return client
