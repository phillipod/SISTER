from sister_website.models import db, User, Submission, Build, Screenshot, AcceptanceState
from .test_auth import register, login
from .test_submission_routes import create_image_bytes


def create_user_submission(app, email):
    with app.app_context():
        submission = Submission(
            email=email,
            acceptance_token='tok123',
            acceptance_state=AcceptanceState.ACCEPTED,
        )
        build = Build(submission=submission, platform='PC', type='space')
        sc = Screenshot(build=build, filename='img.png', md5sum='x', data=create_image_bytes().getvalue())
        db.session.add_all([submission, build, sc])
        db.session.commit()
        return submission


def test_user_submission_browser(client, app):
    register(client)
    with app.app_context():
        user = User.query.filter_by(email='user@example.com').first()
        token = user.email_verification_token
    client.get(f'/verify_email/{token}')
    login(client)
    create_user_submission(app, 'user@example.com')
    resp = client.get('/me/submissions')
    assert resp.status_code == 200
    resp = client.get('/api/me/submissions_data')
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)
