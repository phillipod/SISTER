import os
import io
import pytest
from sister_website.app import create_app
from sister_website.models import db, AdminUser
import sister_website.email_utils as email_utils

@pytest.fixture
def app(tmp_path):
    os.environ['SECRET_KEY'] = 'test-secret'
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    os.environ['UPLOAD_FOLDER'] = str(tmp_path)
    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def admin_user(app):
    with app.app_context():
        admin = AdminUser(username='admin')
        admin.set_password('password')
        db.session.add(admin)
        db.session.commit()
        return admin

@pytest.fixture(autouse=True)
def mock_email(monkeypatch):
    for name in ['send_consent_email', 'send_reply_confirmation_email', 'send_verification_email', 'send_password_reset_email']:
        monkeypatch.setattr(email_utils, name, lambda *args, **kwargs: True)
    yield

