import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import json
import uuid

from sister_website.models import (
    User, AdminUser, Submission, Build, Screenshot, AcceptanceState, 
    EmailLog, LinkLog, db
)
from sister_website.forms import NormalUserForm, EditNormalUserForm, UserPasswordForm


def create_normal_user(app, email="test@example.com", password="password", **kwargs):
    """Helper to create a normal user for testing."""
    with app.app_context():
        user = User(email=email)
        user.set_password(password)
        
        # Set optional attributes
        for key, value in kwargs.items():
            setattr(user, key, value)
        
        db.session.add(user)
        db.session.commit()
        return user.id, user.email


def create_admin_user(app, username="testadmin", password="password"):
    """Helper to create an admin user for testing."""
    with app.app_context():
        admin = AdminUser(username=username)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        return admin.id, admin.username


def login_admin(client, username, password):
    """Helper to log in as admin."""
    return client.post('/admin/login', data={
        'username': username,
        'password': password,
        'csrf_token': 'test'
    })


# ===== ADMIN NORMAL USER MANAGEMENT TESTS =====

def test_admin_normal_users_page_requires_login(client, app):
    """Test normal users page requires authentication."""
    response = client.get('/admin/normal-users')
    assert response.status_code == 302  # Redirect to login


def test_admin_normal_users_page_authenticated(client, app, admin_user):
    """Test normal users page with authentication."""
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.get('/admin/normal-users')
    assert response.status_code == 200
    assert b'Normal User Management' in response.data


def test_admin_normal_users_displays_users(client, app, admin_user):
    """Test that normal users are displayed in the management interface."""
    # Create some test users
    user_id1, user_email1 = create_normal_user(app, "user1@test.com", "password1")
    user_id2, user_email2 = create_normal_user(app, "user2@test.com", "password2", email_verified=True)
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.get('/admin/normal-users')
    assert response.status_code == 200
    assert user_email1.encode() in response.data
    assert user_email2.encode() in response.data
    assert b'Verified' in response.data  # Should show verified status


def test_create_normal_user_success(client, app, admin_user):
    """Test creating a new normal user."""
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post('/admin/normal-users', data={
        'email': 'newuser@test.com',
        'password': 'newpassword123',
        'confirm_password': 'newpassword123',
        'email_verified': True,
        'contributor_recognition_enabled': True,
        'contributor_recognition_text': 'Test User',
        'contributor_recognition_verified': True,
        'csrf_token': 'test'
    })
    assert response.status_code == 302  # Redirect after creation
    
    # Verify user was created
    with app.app_context():
        new_user = User.query.filter_by(email='newuser@test.com').first()
        assert new_user is not None
        assert new_user.check_password('newpassword123')
        assert new_user.email_verified is True
        assert new_user.contributor_recognition_enabled is True
        assert new_user.contributor_recognition_text == 'Test User'
        assert new_user.contributor_recognition_verified is True


def test_create_normal_user_duplicate_email(client, app, admin_user):
    """Test creating a user with duplicate email fails."""
    create_normal_user(app, "existing@test.com", "password")
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post('/admin/normal-users', data={
        'email': 'existing@test.com',
        'password': 'newpassword123',
        'confirm_password': 'newpassword123',
        'csrf_token': 'test'
    })
    assert response.status_code == 200  # Stays on page due to form error
    assert b'already taken' in response.data


def test_edit_normal_user_success(client, app, admin_user):
    """Test editing a normal user."""
    user_id, user_email = create_normal_user(app, "edit@test.com", "password")
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post(f'/admin/normal-user/{user_id}/edit', data={
        'email': 'edited@test.com',
        'email_verified': True,
        'contributor_recognition_enabled': True,
        'contributor_recognition_text': 'Edited User',
        'contributor_recognition_verified': True,
        'csrf_token': 'test'
    })
    assert response.status_code == 302  # Redirect after success
    
    # Verify user was updated
    with app.app_context():
        user = User.query.get(user_id)
        assert user.email == 'edited@test.com'
        assert user.email_verified is True
        assert user.contributor_recognition_enabled is True
        assert user.contributor_recognition_text == 'Edited User'
        assert user.contributor_recognition_verified is True


def test_edit_normal_user_page_loads(client, app, admin_user):
    """Test edit user page loads with correct data."""
    user_id, user_email = create_normal_user(
        app, "edit@test.com", "password", 
        email_verified=True, 
        contributor_recognition_text="Original Text"
    )
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.get(f'/admin/normal-user/{user_id}/edit')
    assert response.status_code == 200
    assert b'Edit User' in response.data
    assert b'edit@test.com' in response.data
    assert b'Original Text' in response.data


def test_change_normal_user_password_success(client, app, admin_user):
    """Test changing a normal user's password."""
    user_id, user_email = create_normal_user(app, "password@test.com", "oldpassword")
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post(f'/admin/normal-user/{user_id}/change-password', data={
        'password': 'newpassword123',
        'confirm_password': 'newpassword123',
        'csrf_token': 'test'
    })
    assert response.status_code == 302  # Redirect after success
    
    # Verify password was changed
    with app.app_context():
        user = User.query.get(user_id)
        assert user.check_password('newpassword123')
        assert not user.check_password('oldpassword')


def test_lock_normal_user_success(client, app, admin_user):
    """Test locking a normal user."""
    user_id, user_email = create_normal_user(app, "lock@test.com", "password")
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post(f'/admin/normal-user/{user_id}/lock')
    assert response.status_code == 302  # Redirect after success
    
    # Verify user was locked
    with app.app_context():
        user = User.query.get(user_id)
        assert user.is_locked is True


def test_unlock_normal_user_success(client, app, admin_user):
    """Test unlocking a normal user."""
    user_id, user_email = create_normal_user(app, "unlock@test.com", "password", is_locked=True)
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post(f'/admin/normal-user/{user_id}/unlock')
    assert response.status_code == 302  # Redirect after success
    
    # Verify user was unlocked
    with app.app_context():
        user = User.query.get(user_id)
        assert user.is_locked is False


def test_verify_normal_user_email_success(client, app, admin_user):
    """Test verifying a normal user's email."""
    user_id, user_email = create_normal_user(app, "verify@test.com", "password", email_verified=False)
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post(f'/admin/normal-user/{user_id}/verify-email')
    assert response.status_code == 302  # Redirect after success
    
    # Verify email was verified
    with app.app_context():
        user = User.query.get(user_id)
        assert user.email_verified is True
        assert user.email_verification_token is None


def test_unverify_normal_user_email_success(client, app, admin_user):
    """Test unverifying a normal user's email."""
    user_id, user_email = create_normal_user(app, "unverify@test.com", "password", email_verified=True)
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post(f'/admin/normal-user/{user_id}/unverify-email')
    assert response.status_code == 302  # Redirect after success
    
    # Verify email verification was removed
    with app.app_context():
        user = User.query.get(user_id)
        assert user.email_verified is False


def test_delete_normal_user_success(client, app, admin_user):
    """Test deleting a normal user."""
    user_id, user_email = create_normal_user(app, "delete@test.com", "password")
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post(f'/admin/normal-user/{user_id}/delete')
    assert response.status_code == 302  # Redirect after success
    
    # Verify user was deleted
    with app.app_context():
        user = User.query.get(user_id)
        assert user is None


def test_delete_normal_user_with_submissions(client, app, admin_user):
    """Test deleting a normal user with associated submissions."""
    user_id, user_email = create_normal_user(app, "delete_with_data@test.com", "password")
    
    # Create associated data
    with app.app_context():
        user = User.query.get(user_id)
        
        # Create submission
        submission = Submission(
            email=user.email,
            acceptance_token=str(uuid.uuid4())[:16],
            acceptance_state=AcceptanceState.ACCEPTED
        )
        db.session.add(submission)
        db.session.commit()
        
        # Create build
        build = Build(
            submission_id=submission.id,
            platform='test',
            type='test'
        )
        db.session.add(build)
        db.session.commit()
        
        # Create screenshot
        screenshot = Screenshot(
            build_id=build.id,
            filename='test.png',
            md5sum='abc123',
            data=b'test_image_data'
        )
        db.session.add(screenshot)
        
        # Create logs
        email_log = EmailLog(
            submission_id=submission.id,
            from_address='test@test.com',
            to_address=user.email,
            subject='Test'
        )
        db.session.add(email_log)
        
        link_log = LinkLog(
            submission_id=submission.id,
            ip_address='127.0.0.1',
            token_used='test_token'
        )
        db.session.add(link_log)
        
        db.session.commit()
        
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post(f'/admin/normal-user/{user_id}/delete')
    assert response.status_code == 302  # Redirect after success
    
    # Verify user and all associated data was deleted
    with app.app_context():
        user = User.query.get(user_id)
        assert user is None
        
        # Check that associated data is also deleted
        submission = Submission.query.filter_by(email=user_email).first()
        assert submission is None


def test_search_normal_users(client, app, admin_user):
    """Test searching normal users."""
    create_normal_user(app, "searchme@test.com", "password")
    create_normal_user(app, "other@test.com", "password")
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.get('/admin/normal-users?search=searchme')
    assert response.status_code == 200
    assert b'searchme@test.com' in response.data
    assert b'other@test.com' not in response.data


def test_pagination_normal_users(client, app, admin_user):
    """Test pagination of normal users."""
    # Create enough users to trigger pagination (assuming 25 per page)
    for i in range(30):
        create_normal_user(app, f"user{i}@test.com", "password")
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.get('/admin/normal-users')
    assert response.status_code == 200
    assert b'Next' in response.data  # Should have next page link
    
    # Test page 2
    response = client.get('/admin/normal-users?page=2')
    assert response.status_code == 200
    assert b'Previous' in response.data  # Should have previous page link


def test_admin_normal_user_routes_require_admin_auth(client, app):
    """Test that all normal user management routes require admin authentication."""
    user_id, _ = create_normal_user(app, "test@test.com", "password")
    
    routes_to_test = [
        ('/admin/normal-users', 'GET'),
        ('/admin/normal-users', 'POST'),
        (f'/admin/normal-user/{user_id}/edit', 'GET'),
        (f'/admin/normal-user/{user_id}/edit', 'POST'),
        (f'/admin/normal-user/{user_id}/change-password', 'GET'),
        (f'/admin/normal-user/{user_id}/change-password', 'POST'),
        (f'/admin/normal-user/{user_id}/lock', 'POST'),
        (f'/admin/normal-user/{user_id}/unlock', 'POST'),
        (f'/admin/normal-user/{user_id}/delete', 'POST'),
        (f'/admin/normal-user/{user_id}/verify-email', 'POST'),
        (f'/admin/normal-user/{user_id}/unverify-email', 'POST'),
    ]
    
    for route, method in routes_to_test:
        if method == 'GET':
            response = client.get(route)
        else:
            response = client.post(route)
        
        assert response.status_code == 302  # Should redirect to admin login
        assert '/admin/login' in response.location or 'admin/login' in response.headers.get('Location', '')


def test_normal_user_form_validation(app):
    """Test normal user form validation."""
    with app.app_context():
        # Test duplicate email validation
        create_normal_user(app, "existing@test.com", "password")
        
        form = NormalUserForm(data={
            'email': 'existing@test.com',
            'password': 'password',
            'confirm_password': 'password'
        })
        assert not form.validate()
        assert 'already taken' in str(form.email.errors)
        
        # Test password mismatch
        form = NormalUserForm(data={
            'email': 'new@test.com',
            'password': 'password1',
            'confirm_password': 'password2'
        })
        assert not form.validate()
        assert 'Passwords must match' in str(form.password.errors)


def test_edit_normal_user_form_validation(app):
    """Test edit normal user form validation."""
    with app.app_context():
        user_id1, _ = create_normal_user(app, "user1@test.com", "password")
        user_id2, _ = create_normal_user(app, "user2@test.com", "password")
        
        # Test changing to existing email
        form = EditNormalUserForm(original_email="user1@test.com", data={
            'email': 'user2@test.com'
        })
        assert not form.validate()
        assert 'already taken' in str(form.email.errors)
        
        # Test keeping same email should be allowed
        form = EditNormalUserForm(original_email="user1@test.com", data={
            'email': 'user1@test.com'
        })
        form.validate()  # Should not raise validation error for email 