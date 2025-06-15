import io
from flask import url_for
from sister_website.models import db, User


def register(client, email='user@example.com', password='pw1234'):
    return client.post('/register', data={
        'email': email,
        'password': password,
        'confirm_password': password
    }, follow_redirects=True)


def login(client, email='user@example.com', password='pw1234'):
    return client.post('/login', data={
        'email': email,
        'password': password
    }, follow_redirects=True)


def test_register_verify_login_logout(client, app):
    resp = register(client)
    assert resp.status_code == 200
    with app.app_context():
        user = User.query.filter_by(email='user@example.com').first()
        assert user is not None
        token = user.email_verification_token
    client.get(f'/verify_email/{token}')
    resp = login(client)
    assert resp.status_code == 200
    resp = client.get('/logout', follow_redirects=True)
    assert resp.status_code == 200
