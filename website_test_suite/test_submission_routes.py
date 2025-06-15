import io
from PIL import Image
from sister_website.models import db, Submission


def create_image_bytes():
    image = Image.new('RGB', (1, 1), 'white')
    buf = io.BytesIO()
    image.save(buf, format='PNG')
    buf.seek(0)
    return buf


def submit_screenshot(client, email='user@example.com'):
    img = create_image_bytes()
    data = {
        'email': email,
        'agree_to_license': 'y',
        'build_type_0': 'space',
        'build_platform_0': 'PC',
        'screenshots_0': (img, 'test.png'),
    }
    return client.post('/training-data/submit', data=data, content_type='multipart/form-data')


def test_submit_and_accept_decline(client, app):
    resp = submit_screenshot(client)
    assert resp.status_code == 302
    with app.app_context():
        submission = Submission.query.first()
        assert submission is not None
        token1 = submission.acceptance_token
    client.get(f'/api/accept-license/{token1}')
    with app.app_context():
        submission = Submission.query.get(submission.id)
        assert submission.acceptance_state.value == 'accepted'
    resp = submit_screenshot(client, email='user2@example.com')
    with app.app_context():
        submission2 = Submission.query.filter_by(email='user2@example.com').first()
        token2 = submission2.acceptance_token
    client.post(f'/api/decline-license/{token2}')
    with app.app_context():
        submission2 = Submission.query.get(submission2.id)
        assert submission2.acceptance_state.value == 'declined'
