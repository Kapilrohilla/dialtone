import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from knowledge.models import KnowledgeDocument, KnowledgeRevision
from tests.helpers import assert_isolated


def _create(client, title="FAQ", body="hello"):
    return client.post("/api/knowledge", {"title": title, "body_md": body}, format="json")


@pytest.mark.django_db
def test_create_makes_revision_1(member):
    c = member("editor")
    r = _create(c)
    assert r.status_code == 201
    assert r.json()["current_revision"] == 1
    rev = KnowledgeRevision.objects.get(document_id=r.json()["id"])
    assert rev.number == 1 and rev.body_md == "hello" and rev.edited_by == c.user
    lst = c.get("/api/knowledge").json()
    assert set(lst[0]) == {"id", "title", "updated_at", "current_revision"}


@pytest.mark.django_db
def test_save_same_body_no_new_revision(member):
    c = member("editor")
    pk = _create(c).json()["id"]
    r = c.patch(f"/api/knowledge/{pk}", {"body_md": "hello"}, format="json")
    assert r.status_code == 200 and r.json()["current_revision"] == 1
    c.patch(f"/api/knowledge/{pk}", {"title": "New title"}, format="json")
    assert KnowledgeRevision.objects.filter(document_id=pk).count() == 1
    assert c.get(f"/api/knowledge/{pk}").json()["title"] == "New title"


@pytest.mark.django_db
def test_save_changed_body_increments(member):
    c = member("editor")
    pk = _create(c).json()["id"]
    r = c.patch(f"/api/knowledge/{pk}", {"body_md": "v2"}, format="json")
    assert r.json()["current_revision"] == 2 and r.json()["body_md"] == "v2"
    revs = c.get(f"/api/knowledge/{pk}/revisions").json()
    assert [x["number"] for x in revs] == [2, 1]
    one = c.get(f"/api/knowledge/{pk}/revisions/1").json()
    assert one["body_md"] == "hello" and one["number"] == 1
    assert c.get(f"/api/knowledge/{pk}/revisions/9").status_code == 404


@pytest.mark.django_db
def test_upload_md_utf8_devanagari(member):
    c = member("editor")
    text = "नमस्ते दुनिया"
    f = SimpleUploadedFile("मार्गदर्शिका.md", text.encode("utf-8"))
    r = c.post("/api/knowledge/upload", {"file": f}, format="multipart")
    assert r.status_code == 201, r.content
    assert r.json()["title"] == "मार्गदर्शिका"
    assert c.get(f"/api/knowledge/{r.json()['id']}").json()["body_md"] == text


@pytest.mark.django_db
def test_upload_rejects_non_md_and_too_big(member):
    c = member("editor")
    bad = [
        SimpleUploadedFile("a.txt", b"x"),
        SimpleUploadedFile("a.md", b"x" * (1024 * 1024 + 1)),
        SimpleUploadedFile("a.md", b"\xff\xfe\x00bad"),
    ]
    for f in bad:
        r = c.post("/api/knowledge/upload", {"file": f}, format="multipart")
        assert r.status_code == 400 and r.json()["detail"]
    assert c.post("/api/knowledge/upload", {}, format="multipart").status_code == 400
    assert KnowledgeDocument.objects.count() == 0


@pytest.mark.django_db
def test_viewer_cannot_save(member):
    e, v = member("editor"), member("viewer")
    pk = _create(e).json()["id"]
    assert v.patch(f"/api/knowledge/{pk}", {"body_md": "x"}, format="json").status_code == 403
    assert v.post("/api/knowledge", {"title": "t", "body_md": ""}, format="json").status_code == 403
    assert v.get(f"/api/knowledge/{pk}").status_code == 200
    assert v.get("/api/knowledge").status_code == 200
    assert v.get(f"/api/knowledge/{pk}/revisions").status_code == 200


@pytest.mark.django_db
def test_knowledge_isolated(member, other_workspace):
    doc = KnowledgeDocument.objects.create(workspace=other_workspace, title="x")
    KnowledgeRevision.objects.create(document=doc, number=1, body_md="s")
    c = member("editor")
    assert_isolated(c, f"/api/knowledge/{doc.id}")
    assert_isolated(c, f"/api/knowledge/{doc.id}/revisions")
    assert_isolated(c, f"/api/knowledge/{doc.id}/revisions/1")
    assert c.patch(f"/api/knowledge/{doc.id}", {"title": "y"}, format="json").status_code == 404
    assert c.get("/api/knowledge").json() == []
