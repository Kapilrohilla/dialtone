import struct
import zlib

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from instance.logo import LogoError, check_logo, sanitize_svg
from instance.models import InstanceSettings

pytestmark = pytest.mark.django_db


def png(width=64, height=64):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def jpeg(width=32, height=32):
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="#2563EB"/></svg>'


@pytest.fixture
def superuser():
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_superuser(username="root", email="root@example.com", password="pw-1234567")
    client = APIClient()
    client.force_login(user)
    client.user = user
    return client


def upload(client, data, name="logo.png"):
    return client.post("/api/instance/logo", {"file": SimpleUploadedFile(name, data)}, format="multipart")


@pytest.mark.parametrize("data, content_type", [(png(), "image/png"), (jpeg(), "image/jpeg"), (SVG, "image/svg+xml")])
def test_superuser_uploads_then_everyone_sees_it(superuser, data, content_type):
    r = upload(superuser, data)
    assert r.status_code == 200, r.content
    url = r.json()["logo_url"]
    assert url.startswith("/api/instance/logo?v=")
    assert APIClient().get("/api/instance").json()["logo_url"] == url

    got = APIClient().get(url)
    assert got.status_code == 200 and got["Content-Type"] == content_type
    assert got["X-Content-Type-Options"] == "nosniff" and "sandbox" in got["Content-Security-Policy"]
    assert "max-age" in got["Cache-Control"]
    if content_type != "image/svg+xml":
        assert got.content == data
    assert InstanceSettings.load().updated_by == superuser.user


def test_new_upload_changes_the_url(superuser):
    first = upload(superuser, png()).json()["logo_url"]
    second = upload(superuser, png(32, 32)).json()["logo_url"]
    assert first != second
    assert APIClient().get(first)["Cache-Control"] == "no-cache"


def test_no_logo_is_404():
    assert APIClient().get("/api/instance/logo").status_code == 404


def test_remove(superuser):
    upload(superuser, png())
    r = superuser.delete("/api/instance/logo")
    assert r.status_code == 200 and r.json()["logo_url"] is None
    assert APIClient().get("/api/instance/logo").status_code == 404
    row = InstanceSettings.load(with_logo=True)
    assert row.logo is None and row.logo_version == ""


def test_upload_keeps_name_and_theme(superuser):
    InstanceSettings.objects.update(project_name="Acme", theme="forest")
    body = upload(superuser, png()).json()
    assert body["project_name"] == "Acme" and body["theme"] == "forest"


@pytest.mark.parametrize("role", ["owner", "admin", "editor", "viewer"])
def test_workspace_roles_cannot_upload_or_remove(member, superuser, role):
    upload(superuser, png())
    version = InstanceSettings.load().logo_version
    c = member(role)
    assert upload(c, png(32, 32)).status_code == 403
    assert c.delete("/api/instance/logo").status_code == 403
    assert InstanceSettings.load().logo_version == version


def test_anonymous_cannot_upload():
    assert upload(APIClient(), png()).status_code == 403
    assert InstanceSettings.load().logo_version == ""


@pytest.mark.parametrize("data, message", [
    (b"GIF89a\x01\x00\x01\x00", "PNG, SVG or JPG"),
    (b"%PDF-1.4 hello", "PNG, SVG or JPG"),
    (b"", "empty"),
    (png(64, 32), "must be square"),
    (jpeg(100, 50), "must be square"),
    (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20"/>', "must be square"),
    (b'<svg xmlns="http://www.w3.org/2000/svg"/>', "size"),
    (b"<svg", "couldn't be read"),
    (b'<!DOCTYPE svg [<!ENTITY x "y">]><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1">&x;</svg>', "DOCTYPE"),
    (b'<html xmlns="http://www.w3.org/1999/xhtml"><svg/></html>', "PNG, SVG or JPG"),
])
def test_bad_files_rejected(superuser, data, message):
    r = upload(superuser, data)
    assert r.status_code == 400, r.content
    assert message in r.json()["file"][0]
    assert InstanceSettings.load().logo_version == ""


def test_type_comes_from_the_bytes_not_the_name(superuser):
    r = upload(superuser, b"GIF89a....", name="logo.png")
    assert r.status_code == 400
    assert upload(superuser, png(), name="logo.svg").status_code == 200
    assert APIClient().get("/api/instance/logo")["Content-Type"] == "image/png"


def test_over_one_megabyte_rejected(superuser):
    big = png() + b"\x00" * (1024 * 1024)
    r = upload(superuser, big)
    assert r.status_code == 400 and "1 MB" in r.json()["file"][0]


def test_exactly_one_megabyte_allowed(superuser):
    data = png()
    data += b"\x00" * (1024 * 1024 - len(data))  # trailing bytes after IEND are ignored by readers
    assert upload(superuser, data).status_code == 200


def test_missing_file(superuser):
    r = superuser.post("/api/instance/logo", {}, format="multipart")
    assert r.status_code == 400 and "file" in r.json()


def test_nearly_square_is_fine():
    check_logo(png(512, 508))
    with pytest.raises(LogoError):
        check_logo(png(512, 480))


def test_svg_is_sanitized(superuser):
    evil = b"""<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="48" height="48" onload="alert(1)">
  <script>alert(2)</script>
  <style>@import url(https://evil.example/x.css); .a { fill: red }</style>
  <defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient></defs>
  <a href="javascript:alert(3)"><text>link</text></a>
  <rect width="10" height="10" fill="url(#g)"/>
  <foreignObject><div xmlns="http://www.w3.org/1999/xhtml">hi</div></foreignObject>
  <image href="https://evil.example/track.png" width="1" height="1"/>
  <use xlink:href="#g"/>
  <use href="https://evil.example/sprite.svg#a"/>
  <circle r="4" style="fill: url(https://evil.example/x)" onclick="alert(4)"/>
  <animate attributeName="href" to="javascript:alert(5)"/>
</svg>"""
    r = upload(superuser, evil, name="logo.svg")
    assert r.status_code == 200, r.content
    body = APIClient().get(r.json()["logo_url"]).content
    lowered = body.lower()
    for bad in [b"script", b"onload", b"onclick", b"javascript", b"evil.example", b"foreignobject", b"<image", b"<a ", b"animate", b"@import"]:
        assert bad not in lowered, bad
    assert b'fill="url(#g)"' in body and b'xlink:href="#g"' in body and b"<rect" in body
    assert body.startswith(b"<svg ") and b'xmlns="http://www.w3.org/2000/svg"' in body


def test_sanitized_svg_size():
    _, size = sanitize_svg(b'<svg xmlns="http://www.w3.org/2000/svg" width="48px" height="48"/>')
    assert size == (48, 48)
    _, size = sanitize_svg(b'\xef\xbb\xbf<svg xmlns="http://www.w3.org/2000/svg" viewBox="0,0,10,10"/>')
    assert size == (10, 10)
