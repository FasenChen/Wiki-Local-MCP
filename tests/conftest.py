import pytest


class FakeClient:
    def __init__(self):
        self.pages = {}
        self.search_response = {"results": [], "totalSize": 0}
        self.search_calls = []
        self.spaces_response = {"results": [], "size": 0}
        self.comments = {}
        self.children = {}
        self.versions = {}
        self.historical_pages = {}
        self.created = []
        self.create_response = {}
        self.updated = []
        self.update_response = {}

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

    def get_comments(self, page_id, *, limit):
        self.search_calls.append(("comments", page_id, limit))
        return self.comments.get(page_id, [])

    def get_child_pages(self, page_id, *, limit):
        self.search_calls.append(("children", page_id, limit))
        return self.children.get(page_id, [])[:limit]

    def list_versions(self, page_id):
        self.search_calls.append(("versions", page_id, 0))
        return self.versions.get(page_id, [])

    def get_page_version(self, page_id, version):
        self.search_calls.append(("version", page_id, version))
        try:
            return self.historical_pages[(page_id, version)]
        except KeyError:
            from confluence_mcp.client import ConfluenceAPIError

            raise ConfluenceAPIError("not found", status_code=404) from None

    def create_content(self, payload):
        self.created.append(payload)
        return self.create_response

    def update_page(self, page_id, payload):
        self.updated.append(payload)
        return self.update_response

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
