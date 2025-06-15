import io
import hashlib
import hmac
from PIL import Image
from werkzeug.datastructures import FileStorage
import pytest

from sister_website.app import (
    allowed_mime,
    save_screenshot,
    generate_acceptance_token,
    generate_screenshot_thumbnail,
    is_safe_url,
    is_admin,
    get_forwardemail_ips,
    _fetch_forwardemail_ips,
    _forwardemail_ips,
    _forwardemail_ips_last_fetch,
)
from sister_website.models import AdminUser, db


def create_png_file():
    image = Image.new("RGB", (10, 10), "white")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    buf.seek(0)
    return buf


def test_generate_acceptance_token(app):
    with app.app_context():
        token = generate_acceptance_token("abc", "user@example.com")
        expected = hmac.new(
            app.config["SECRET_KEY"].encode("utf-8"),
            b"abc:user@example.com",
            hashlib.sha256,
        ).hexdigest()
        assert token == expected


def test_allowed_mime_valid_and_invalid(app):
    with app.test_request_context('/'):
        buf = create_png_file()
        fs = FileStorage(stream=io.BytesIO(buf.getvalue()), filename='img.png')
        assert allowed_mime(fs) == 'image/png'
        fs2 = FileStorage(stream=io.BytesIO(b'not an image'), filename='x.txt')
        assert allowed_mime(fs2) is None
        # ensure streams reset
        assert fs.read() == buf.getvalue()
        assert fs2.read() == b'not an image'


def test_save_screenshot_success_and_fail(app):
    with app.app_context():
        buf = create_png_file()
        fs = FileStorage(stream=io.BytesIO(buf.getvalue()), filename='img.png')
        sc = save_screenshot(fs, filename_base='testfile')
        assert sc is not None
        assert sc.filename == 'testfile.png'
        assert sc.md5sum == hashlib.md5(buf.getvalue()).hexdigest()
        assert sc.data == buf.getvalue()
        assert sc.thumbnail_data is not None
        bad = FileStorage(stream=io.BytesIO(b'bad'), filename='bad.bin')
        assert save_screenshot(bad) is None


def test_generate_screenshot_thumbnail(app):
    with app.app_context():
        buf = create_png_file().getvalue()
        thumb = generate_screenshot_thumbnail(buf)
        assert isinstance(thumb, bytes)
        img = Image.open(io.BytesIO(thumb))
        assert max(img.size) <= 240


def test_is_safe_url(app):
    with app.test_request_context('/', base_url='http://example.com'):
        assert is_safe_url('/next')
        assert is_safe_url('http://example.com/next')
        assert not is_safe_url('http://evil.com/')


def test_is_admin(app):
    with app.test_request_context('/'):
        admin = AdminUser(username='a')
        admin.set_password('p')
        db.session.add(admin)
        db.session.commit()
        from flask import session
        session['admin_user_id'] = admin.id
        assert is_admin()
        session['admin_user_id'] = 'notreal'
        assert not is_admin()
        session.pop('admin_user_id')
        assert not is_admin()


def test_get_forwardemail_ips_cached(monkeypatch, app):
    calls = []

    def fake_fetch():
        calls.append(1)
        return ['1.1.1.1']

    with app.app_context():
        monkeypatch.setattr('sister_website.app._fetch_forwardemail_ips', fake_fetch)
        global _forwardemail_ips, _forwardemail_ips_last_fetch
        _forwardemail_ips = []
        _forwardemail_ips_last_fetch = None
        assert get_forwardemail_ips() == ['1.1.1.1']
        assert get_forwardemail_ips() == ['1.1.1.1']
        assert len(calls) == 1
