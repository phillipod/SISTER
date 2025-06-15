from datetime import datetime, timedelta

from sister_website.models import User, AdminUser, Submission, db


def test_user_password_and_tokens(app):
    with app.app_context():
        user = User(email='test@example.com')
        user.set_password('secret')
        db.session.add(user)
        db.session.commit()
        assert user.check_password('secret')
        assert not user.check_password('wrong')

        token = user.generate_verification_token()
        assert user.email_verification_token == token

        reset_token = user.generate_password_reset_token()
        assert user.password_reset_token == reset_token
        assert user.is_password_reset_token_valid()
        user.password_reset_token_expiry = datetime.utcnow() - timedelta(hours=2)
        assert not user.is_password_reset_token_valid()
        user.clear_password_reset_token()
        assert user.password_reset_token is None
        assert user.password_reset_token_expiry is None

        sub1 = Submission(email='test@example.com', acceptance_token='t1')
        sub2 = Submission(email='test@example.com', acceptance_token='t2')
        db.session.add_all([sub1, sub2])
        db.session.commit()
        subs = user.submissions
        assert [s.id for s in subs] == [sub2.id, sub1.id]


def test_admin_user_password(app):
    with app.app_context():
        admin = AdminUser(username='admin')
        admin.set_password('pw')
        assert admin.check_password('pw')
        assert not admin.check_password('other')
