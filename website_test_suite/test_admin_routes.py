from sister_website.models import db, DatasetLabel, Submission, Build, Screenshot, AcceptanceState
from .test_submission_routes import create_image_bytes


def create_accepted_submission(app):
    with app.app_context():
        submission = Submission(email='admin@test', acceptance_token='t1', acceptance_state=AcceptanceState.ACCEPTED)
        build = Build(submission=submission, platform='PC', type='space')
        sc = Screenshot(build=build, filename='img.png', md5sum='x', data=create_image_bytes().getvalue())
        db.session.add_all([submission, build, sc])
        db.session.commit()


def admin_login(client):
    return client.post('/admin/login', data={'username': 'admin', 'password': 'password'}, follow_redirects=True)


def test_admin_dataset_label_and_manager(client, app, admin_user):
    admin_login(client)
    resp = client.post('/admin/dataset-labels', data={'name': 'Label1', 'description': 'd'}, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        assert DatasetLabel.query.filter_by(name='Label1').first() is not None
    resp = client.get('/admin/dataset-labels')
    assert resp.status_code == 200

    create_accepted_submission(app)
    resp = client.get('/admin/dataset-manager')
    assert resp.status_code == 200


def test_admin_submission_browser(client, app, admin_user):
    create_accepted_submission(app)
    admin_login(client)
    resp = client.get('/admin/submissions')
    assert resp.status_code == 200
    resp = client.get('/admin/api/submissions')
    assert resp.status_code == 200
