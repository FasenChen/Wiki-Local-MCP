from confluence_mcp import server


def test_get_comments_returns_author_body_and_parent(fake_client):
    fake_client.comments["42"] = [
        {
            "id": "99",
            "ancestors": [],
            "history": {
                "createdBy": {"displayName": "Alice"},
                "createdDate": "2026-10-01T10:00:00.000Z",
            },
            "body": {"storage": {"value": "<p>first</p>"}},
        },
        {
            "id": "100",
            "ancestors": [{"id": "42", "type": "page"}, {"id": "99", "type": "comment"}],
            "history": {
                "createdBy": {"displayName": "Bob"},
                "createdDate": "2026-10-02T10:00:00.000Z",
            },
            "body": {"storage": {"value": "<p>reply</p>"}},
        },
    ]

    result = server.get_comments("42", limit=50)

    assert result["comments"] == [
        {
            "comment_id": "99",
            "author": "Alice",
            "created": "2026-10-01T10:00:00.000Z",
            "parent_comment_id": None,
            "content": "first",
        },
        {
            "comment_id": "100",
            "author": "Bob",
            "created": "2026-10-02T10:00:00.000Z",
            "parent_comment_id": "99",
            "content": "reply",
        },
    ]
    assert result["count"] == 2
