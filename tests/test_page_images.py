import pytest

from confluence_mcp import apply, queue, server, writes
from confluence_mcp.client import ConfluenceAPIError


@pytest.fixture(autouse=True)
def page_client(fake_client, config_values, monkeypatch, tmp_path):
    config_values["CONFLUENCE_ENABLE_WRITES"] = "true"
    monkeypatch.setattr(writes, "AUDIT_PATH", tmp_path / "audit.log")
    fake_client.pages["42"] = {
        "id": "42", "title": "Guide", "space": {"key": "OPS"}, "version": {"number": 3},
        "body": {"storage": {"value": "<h2>Setup</h2><p>old</p><h2>Keep</h2><p>unchanged</p>"}},
    }
    fake_client.create_response = {"id": "77", "version": {"number": 1}}
    fake_client.update_response = {"id": "42", "version": {"number": 4}}


def _page_image(action, image_file, dry_run=False):
    markdown = f"![流程图]({image_file.name})"
    kwargs = {"image_base_dir": str(image_file.parent), "dry_run": dry_run}
    if action == "create":
        return server.create_page("OPS", "New guide", markdown, **kwargs)
    if action == "section":
        return server.update_page_section("42", "Setup", markdown, expected_version=3, **kwargs)
    return server.update_page("42", expected_version=3, content=markdown, **kwargs)


@pytest.mark.parametrize("action", ["create", "update", "section"])
def test_page_image_dry_run_only_previews_and_queue_only_snapshots(action, fake_client, image_file):
    preview = _page_image(action, image_file, dry_run=True)
    assert preview["attachments"][0]["source"] == str(image_file.resolve())
    assert "ri:attachment" in preview["storage_preview"]
    assert queue.list_ops() == []
    queued = _page_image(action, image_file)
    op = queue.get_op(queued["operation_id"])
    assert op["status"] == "pending" and "ri:attachment" in op["payload"]["body"]["storage"]["value"]
    assert fake_client.created == fake_client.updated == fake_client.uploaded == []
    assert server.get_queued_operations([op["id"]])["operations"][0]["attachments"] == preview["attachments"]


@pytest.mark.parametrize("action", ["create", "update", "section"])
def test_approval_uploads_snapshot_and_publishes_attachment_references_once(action, fake_client, image_file):
    op_id = _page_image(action, image_file)["operation_id"]
    snapshot = image_file.read_bytes()
    image_file.unlink()  # Approval is independent of the original file's lifetime.
    if action == "create":
        fake_client.update_response = {"id": "77", "version": {"number": 2}}
    out = apply.approve_and_apply(fake_client, [op_id])["executed"][0]
    assert out["status"] == "succeeded"
    [upload] = fake_client.uploaded
    assert upload[0] == ("77" if action == "create" else "42") and upload[2] == snapshot
    [published] = fake_client.updated
    assert f'ri:filename="{upload[1]}"' in published["body"]["storage"]["value"]
    assert published["version"]["number"] == (2 if action == "create" else 4)
    assert "uploaded_attachments" not in published
    if action == "create":
        assert "ri:attachment" not in fake_client.created[0]["body"]["storage"]["value"]
        assert out["result"]["id"] == "77"
    if action == "section":
        assert published["body"]["storage"]["value"].endswith("<h2>Keep</h2><p>unchanged</p>")
    assert apply.approve_and_apply(fake_client, [op_id])["executed"] == []
    assert len(fake_client.uploaded) == len(fake_client.updated) == 1


@pytest.mark.parametrize("changed", ["version", "space"])
def test_changed_page_version_or_space_fails_before_any_upload(fake_client, image_file, changed):
    op_id = _page_image("update", image_file)["operation_id"]
    if changed == "version":
        fake_client.pages["42"]["version"]["number"] = 4
    else:
        fake_client.pages["42"]["space"]["key"] = "QA"
    out = apply.approve_and_apply(fake_client, [op_id])["executed"][0]
    assert out["status"] == "failed" and fake_client.uploaded == fake_client.updated == []


def test_existing_content_addressed_attachment_is_reused(fake_client, image_file):
    op_id = _page_image("update", image_file)["operation_id"]
    [image] = queue.get_attachments(op_id)
    fake_client.attachments[("42", image.filename)] = {"id": "100", "title": image.filename}
    out = apply.approve_and_apply(fake_client, [op_id])["executed"][0]
    assert out["status"] == "succeeded" and fake_client.uploaded == []
    assert out["result"]["reused_attachments"] == [image.filename]


def test_failed_upload_keeps_created_page_id_and_stops_before_publishing(fake_client, image_file):
    op_id = _page_image("create", image_file)["operation_id"]

    def denied(*args):
        raise ConfluenceAPIError("upload forbidden", status_code=403)

    fake_client.upload_attachment = denied
    out = apply.approve_and_apply(fake_client, [op_id])["executed"][0]
    assert out["status"] == "failed" and out["result"]["id"] == "77"
    assert out["result"]["page_created"] and out["result"]["uploaded_attachments"] == []
    assert queue.get_op(op_id)["result"] == out["result"]
    assert fake_client.updated == []
    assert '"result": "partial"' in writes.AUDIT_PATH.read_text(encoding="utf-8")


def test_final_version_conflict_records_uploaded_files_without_overwriting_page(fake_client, image_file):
    op_id = _page_image("update", image_file)["operation_id"]

    def conflict(*args):
        raise ConfluenceAPIError("version conflict", status_code=409)

    fake_client.update_page = conflict
    out = apply.approve_and_apply(fake_client, [op_id])["executed"][0]
    assert out["status"] == "failed" and len(fake_client.uploaded) == 1
    assert out["result"]["version"] == 3
    assert out["result"]["uploaded_attachments"] == [fake_client.uploaded[0][1]]
    assert queue.get_op(op_id)["result"] == out["result"]


def test_upload_timeout_preserves_progress_and_stops_batch(fake_client, image_file):
    op_id = _page_image("create", image_file)["operation_id"]
    next_op = server.create_page("OPS", "Next", "body", dry_run=False)["operation_id"]

    def timeout(*args):
        # A crash/timeout must leave the already-known page id durable.
        assert queue.get_op(op_id)["result"]["id"] == "77"
        raise ConfluenceAPIError("timed out")

    fake_client.upload_attachment = timeout
    out = apply.approve_and_apply(fake_client, [op_id, next_op])
    assert out["executed"][0]["status"] == "indeterminate" and out["skipped"] == [next_op]
    assert queue.get_op(next_op)["status"] == "pending"


def test_second_upload_failure_keeps_first_upload_and_pending_filename(fake_client, image_file):
    second = image_file.with_name("second.svg")
    second.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>', encoding="utf-8")
    op_id = server.create_page(
        "OPS", "Two images", f"![a]({image_file.name}) ![b]({second.name})",
        image_base_dir=str(image_file.parent), dry_run=False,
    )["operation_id"]
    original_upload = fake_client.upload_attachment

    def upload(page_id, filename, data, content_type):
        if fake_client.uploaded:
            raise ConfluenceAPIError("denied", status_code=403)
        return original_upload(page_id, filename, data, content_type)

    fake_client.upload_attachment = upload
    result = apply.approve_and_apply(fake_client, [op_id])["executed"][0]
    first_image, second_image = queue.get_attachments(op_id)
    assert result["status"] == "failed" and fake_client.updated == []
    assert result["result"]["uploaded_attachments"] == [first_image.filename]
    assert result["result"]["uploading_attachment"] == second_image.filename
    assert queue.get_op(op_id)["result"] == result["result"]


def test_missing_image_does_not_queue_a_broken_page(fake_client, tmp_path):
    with pytest.raises(ValueError, match="Could not read image"):
        server.create_page("OPS", "New", "![x](missing.png)", image_base_dir=str(tmp_path), dry_run=False)
    assert queue.list_ops() == [] and fake_client.created == []
