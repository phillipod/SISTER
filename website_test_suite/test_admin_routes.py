import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import json
import uuid

from sister_website.models import (
    User, AdminUser, Submission, Build, Screenshot, AcceptanceState, 
    DatasetLabel, BuildAuditLog, EmailLog, LinkLog, db
)
from sister_website.forms import AdminUserForm, DatasetLabelForm
from .test_submission_routes import create_image_bytes


def create_admin_user(app, username="testadmin", password="password"):
    """Helper to create an admin user for testing."""
    with app.app_context():
        admin = AdminUser(username=username)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        return admin.id, admin.username


def login_admin(client, username="admin", password="password"):
    """Helper to login as admin."""
    return client.post('/admin/login', data={
        'username': username,
        'password': password,
        'csrf_token': 'test'
    })


def create_test_submission_with_build(app, email="test@example.com", accepted=True):
    """Helper to create a submission with build and screenshot for testing."""
    with app.app_context():
        submission = Submission(
            email=email,
            acceptance_token='test_token_123',
            acceptance_state=AcceptanceState.ACCEPTED if accepted else AcceptanceState.PENDING
        )
        
        build = Build(
            submission=submission, 
            platform='PC', 
            type='space'
        )
        
        screenshot = Screenshot(
            build=build,
            filename='test_screenshot.png',
            md5sum='test_md5_hash',
            data=create_image_bytes().getvalue()
        )
        
        db.session.add_all([submission, build, screenshot])
        db.session.commit()
        return submission.id, build.id, screenshot.id


def create_test_dataset_label(app, name="Test Label", description="Test Description"):
    """Helper to create a dataset label for testing."""
    with app.app_context():
        label = DatasetLabel(name=name, description=description)
        db.session.add(label)
        db.session.commit()
        return label.id, label.name


def create_accepted_submission(app):
    """Legacy helper for backward compatibility."""
    with app.app_context():
        submission = Submission(email='admin@test', acceptance_token='t1', acceptance_state=AcceptanceState.ACCEPTED)
        build = Build(submission=submission, platform='PC', type='space')
        sc = Screenshot(build=build, filename='img.png', md5sum='x', data=create_image_bytes().getvalue())
        db.session.add_all([submission, build, sc])
        db.session.commit()


def admin_login(client):
    """Legacy helper for backward compatibility."""
    return client.post('/admin/login', data={'username': 'admin', 'password': 'password'}, follow_redirects=True)


# ===== EXISTING TESTS (PRESERVED) =====

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


# ===== NEW COMPREHENSIVE ADMIN TESTS =====

# ===== ADMIN AUTHENTICATION TESTS =====

def test_admin_login_page_get(client, app):
    """Test admin login page loads correctly."""
    response = client.get('/admin/login')
    assert response.status_code == 200
    assert b'Admin Login' in response.data or b'Username' in response.data


def test_admin_login_success(client, app, admin_user):
    """Test successful admin login."""
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    response = client.post('/admin/login', data={
        'username': admin_username,
        'password': 'password',
        'csrf_token': 'test'
    })
    assert response.status_code == 302  # Redirect after successful login


def test_admin_login_invalid_credentials(client, app):
    """Test admin login with invalid credentials."""
    create_admin_user(app, "testadmin", "password")
    
    response = client.post('/admin/login', data={
        'username': 'testadmin',
        'password': 'wrongpassword',
        'csrf_token': 'test'
    })
    assert response.status_code == 200  # Stay on login page
    assert b'Invalid credentials' in response.data or b'error' in response.data.lower()


def test_admin_login_locked_account(client, app):
    """Test admin login with locked account."""
    admin_id, admin_username = create_admin_user(app, "testadmin", "password")
    
    # Lock the admin account
    with app.app_context():
        admin = AdminUser.query.get(admin_id)
        admin.is_locked = True
        db.session.commit()
    
    response = client.post('/admin/login', data={
        'username': admin_username,
        'password': 'password',
        'csrf_token': 'test'
    })
    assert response.status_code == 200  # Stay on login page
    assert b'invalid credentials' in response.data.lower() or b'locked' in response.data.lower() or b'disabled' in response.data.lower()


def test_admin_logout(client, app, admin_user):
    """Test admin logout functionality."""
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    # Login first
    login_admin(client, admin_username, 'password')
    
    # Then logout
    response = client.get('/admin/logout')
    assert response.status_code == 302  # Redirect after logout
    
    # Verify can't access admin pages after logout
    response = client.get('/admin')
    assert response.status_code == 302  # Redirect to login


# ===== ADMIN DASHBOARD TESTS =====

def test_admin_dashboard_requires_login(client, app):
    """Test admin dashboard requires authentication."""
    response = client.get('/admin')
    assert response.status_code == 302  # Redirect to login


def test_admin_dashboard_authenticated(client, app, admin_user):
    """Test admin dashboard with authentication."""
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.get('/admin')
    assert response.status_code == 200
    assert b'Admin Dashboard' in response.data or b'dashboard' in response.data.lower()


# ===== ADMIN USER MANAGEMENT TESTS =====

def test_admin_users_page_requires_login(client, app):
    """Test admin users page requires authentication."""
    response = client.get('/admin/users')
    assert response.status_code == 302  # Redirect to login


def test_admin_users_page_authenticated(client, app, admin_user):
    """Test admin users page with authentication."""
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.get('/admin/users')
    assert response.status_code == 200
    assert b'admin' in response.data.lower()  # Should show existing admin user


def test_create_admin_user_success(client, app, admin_user):
    """Test creating a new admin user."""
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post('/admin/users', data={
        'username': 'newadmin',
        'password': 'newpassword123',
        'confirm_password': 'newpassword123',
        'csrf_token': 'test'
    })
    assert response.status_code == 302  # Redirect after creation
    
    # Verify user was created
    with app.app_context():
        new_admin = AdminUser.query.filter_by(username='newadmin').first()
        assert new_admin is not None
        assert new_admin.check_password('newpassword123')


def test_create_admin_user_duplicate_username(client, app, admin_user):
    """Test creating admin user with duplicate username."""
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post('/admin/users', data={
        'username': 'admin',  # Duplicate username
        'password': 'newpassword123',
        'confirm_password': 'newpassword123',
        'csrf_token': 'test'
    })
    assert response.status_code == 200  # Stay on page with error
    assert b'already taken' in response.data or b'exists' in response.data


def test_create_admin_user_password_mismatch(client, app, admin_user):
    """Test creating admin user with password mismatch."""
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post('/admin/users', data={
        'username': 'newadmin',
        'password': 'password123',
        'confirm_password': 'differentpassword',
        'csrf_token': 'test'
    })
    assert response.status_code == 200  # Stay on page with error
    assert b'match' in response.data.lower()


def test_change_admin_password_success(client, app, admin_user):
    """Test changing admin user password."""
    # Create a second admin user to change password for
    admin_id, admin_username = create_admin_user(app, "testadmin", "oldpassword")
    
    # Login as main admin
    with app.app_context():
        main_admin = AdminUser.query.filter_by(username='admin').first()
        main_admin_username = main_admin.username
    
    login_admin(client, main_admin_username, 'password')
    
    response = client.post(f'/admin/user/{admin_id}/change-password', data={
        'password': 'newpassword123',
        'confirm_password': 'newpassword123',
        'csrf_token': 'test'
    })
    assert response.status_code == 302  # Redirect after success
    
    # Verify password was changed
    with app.app_context():
        admin = AdminUser.query.get(admin_id)
        assert admin.check_password('newpassword123')
        assert not admin.check_password('oldpassword')


def test_lock_admin_user_success(client, app, admin_user):
    """Test locking an admin user."""
    # Create a second admin user to lock
    admin_id, admin_username = create_admin_user(app, "testadmin", "password")
    
    # Login as main admin
    with app.app_context():
        main_admin = AdminUser.query.filter_by(username='admin').first()
        main_admin_username = main_admin.username
    
    login_admin(client, main_admin_username, 'password')
    
    response = client.post(f'/admin/user/{admin_id}/lock')
    assert response.status_code == 302  # Redirect after success
    
    # Verify user was locked
    with app.app_context():
        admin = AdminUser.query.get(admin_id)
        assert admin.is_locked is True


def test_lock_admin_user_self_prevention(client, app, admin_user):
    """Test that admin cannot lock their own account."""
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
        admin_id = admin.id
    
    login_admin(client, admin_username, 'password')
    
    response = client.post(f'/admin/user/{admin_id}/lock')
    assert response.status_code == 302  # Redirect with error message
    
    # Verify user was not locked
    with app.app_context():
        admin = AdminUser.query.get(admin_id)
        assert admin.is_locked is False


def test_unlock_admin_user_success(client, app, admin_user):
    """Test unlocking an admin user."""
    # Create a locked admin user
    admin_id, admin_username = create_admin_user(app, "testadmin", "password")
    with app.app_context():
        admin = AdminUser.query.get(admin_id)
        admin.is_locked = True
        db.session.commit()
    
    # Login as main admin
    with app.app_context():
        main_admin = AdminUser.query.filter_by(username='admin').first()
        main_admin_username = main_admin.username
    
    login_admin(client, main_admin_username, 'password')
    
    response = client.post(f'/admin/user/{admin_id}/unlock')
    assert response.status_code == 302  # Redirect after success
    
    # Verify user was unlocked
    with app.app_context():
        admin = AdminUser.query.get(admin_id)
        assert admin.is_locked is False


def test_delete_admin_user_success(client, app, admin_user):
    """Test deleting an admin user."""
    # Create a second admin user to delete
    admin_id, admin_username = create_admin_user(app, "testadmin", "password")
    
    # Login as main admin
    with app.app_context():
        main_admin = AdminUser.query.filter_by(username='admin').first()
        main_admin_username = main_admin.username
    
    login_admin(client, main_admin_username, 'password')
    
    response = client.post(f'/admin/user/{admin_id}/delete')
    assert response.status_code == 302  # Redirect after success
    
    # Verify user was deleted
    with app.app_context():
        admin = AdminUser.query.get(admin_id)
        assert admin is None


def test_delete_admin_user_self_prevention(client, app, admin_user):
    """Test that admin cannot delete their own account."""
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
        admin_id = admin.id
    
    login_admin(client, admin_username, 'password')
    
    response = client.post(f'/admin/user/{admin_id}/delete')
    assert response.status_code == 302  # Redirect with error message
    
    # Verify user was not deleted
    with app.app_context():
        admin = AdminUser.query.get(admin_id)
        assert admin is not None


# ===== ADMIN SUBMISSIONS BROWSER TESTS =====

def test_admin_submissions_page_requires_login(client, app):
    """Test admin submissions page requires authentication."""
    response = client.get('/admin/submissions')
    assert response.status_code == 302  # Redirect to login


def test_admin_submissions_page_authenticated(client, app, admin_user):
    """Test admin submissions page with authentication."""
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.get('/admin/submissions')
    assert response.status_code == 200
    assert b'submissions' in response.data.lower()


def test_admin_submissions_api_requires_login(client, app):
    """Test admin submissions API requires authentication."""
    response = client.get('/admin/api/submissions')
    assert response.status_code == 403  # Forbidden


def test_admin_submissions_api_authenticated(client, app, admin_user):
    """Test admin submissions API with authentication."""
    # Create test data
    create_test_submission_with_build(app, "test@example.com", accepted=True)
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.get('/admin/api/submissions')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert isinstance(data, list)
    if data:  # If there's data, verify structure
        assert 'submission_id' in data[0]
        assert 'email' in data[0]
        assert 'acceptance_state' in data[0]


def test_admin_screenshot_info_api(client, app, admin_user):
    """Test admin screenshot info API."""
    submission_id, build_id, screenshot_id = create_test_submission_with_build(app)
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.get(f'/admin/api/screenshot_info/{screenshot_id}')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert 'id' in data
    assert 'filename' in data
    assert 'is_accepted' in data


def test_admin_screenshot_info_api_not_found(client, app, admin_user):
    """Test admin screenshot info API with non-existent screenshot."""
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.get('/admin/api/screenshot_info/999999')
    assert response.status_code == 404


# ===== ADMIN DATASET MANAGEMENT TESTS =====

def test_admin_dataset_labels_page_requires_login(client, app):
    """Test admin dataset labels page requires authentication."""
    response = client.get('/admin/dataset-labels')
    assert response.status_code == 302  # Redirect to login


def test_admin_dataset_labels_page_authenticated(client, app, admin_user):
    """Test admin dataset labels page with authentication."""
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.get('/admin/dataset-labels')
    assert response.status_code == 200
    assert b'dataset' in response.data.lower() or b'label' in response.data.lower()


def test_create_dataset_label_success(client, app, admin_user):
    """Test creating a new dataset label."""
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post('/admin/dataset-labels', data={
        'name': 'Test Label',
        'description': 'Test Description',
        'csrf_token': 'test'
    })
    assert response.status_code == 302  # Redirect after creation
    
    # Verify label was created
    with app.app_context():
        label = DatasetLabel.query.filter_by(name='Test Label').first()
        assert label is not None
        assert label.description == 'Test Description'


def test_create_dataset_label_duplicate_name(client, app, admin_user):
    """Test creating dataset label with duplicate name."""
    # Create existing label
    create_test_dataset_label(app, "Existing Label")
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post('/admin/dataset-labels', data={
        'name': 'Existing Label',  # Duplicate name
        'description': 'Test Description',
        'csrf_token': 'test'
    })
    assert response.status_code == 200  # Stay on page with error
    assert b'already exists' in response.data or b'taken' in response.data


def test_edit_dataset_label_success(client, app, admin_user):
    """Test editing a dataset label."""
    label_id, label_name = create_test_dataset_label(app, "Original Label", "Original Description")
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post(f'/admin/dataset-labels/edit/{label_id}', data={
        'name': 'Updated Label',
        'description': 'Updated Description',
        'csrf_token': 'test'
    })
    assert response.status_code == 302  # Redirect after update
    
    # Verify label was updated
    with app.app_context():
        label = DatasetLabel.query.get(label_id)
        assert label.name == 'Updated Label'
        assert label.description == 'Updated Description'


def test_edit_dataset_label_not_found(client, app, admin_user):
    """Test editing non-existent dataset label."""
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.get('/admin/dataset-labels/edit/999999')
    assert response.status_code == 404


def test_toggle_dataset_label_active(client, app, admin_user):
    """Test toggling dataset label active status."""
    label_id, label_name = create_test_dataset_label(app, "Test Label")
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post(f'/admin/dataset-labels/toggle-active/{label_id}')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert 'success' in data
    assert 'is_active' in data
    
    # Verify status was toggled
    with app.app_context():
        label = DatasetLabel.query.get(label_id)
        assert label.is_active == data['is_active']


def test_dataset_manager_page_requires_login(client, app):
    """Test dataset manager page requires authentication."""
    response = client.get('/admin/dataset-manager')
    assert response.status_code == 302  # Redirect to login


def test_dataset_manager_page_authenticated(client, app, admin_user):
    """Test dataset manager page with authentication."""
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.get('/admin/dataset-manager')
    assert response.status_code == 200
    assert b'dataset' in response.data.lower() or b'manager' in response.data.lower()


def test_dataset_manager_with_filters(client, app, admin_user):
    """Test dataset manager with filter parameters."""
    # Create test data
    create_test_submission_with_build(app, "test@example.com", accepted=True)
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.get('/admin/dataset-manager?platform=PC&type=space')
    assert response.status_code == 200


def test_set_build_dataset_label_success(client, app, admin_user):
    """Test setting dataset label for a build."""
    submission_id, build_id, screenshot_id = create_test_submission_with_build(app)
    label_id, label_name = create_test_dataset_label(app, "Test Label")
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
        admin_id = admin.id
    
    login_admin(client, admin_username, 'password')
    
    response = client.post(f'/admin/api/builds/{build_id}/set-label', 
                          json={'label_id': label_id})
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert data['success'] is True
    assert data['label_id'] == label_id
    
    # Verify label was set and audit log created
    with app.app_context():
        build = Build.query.get(build_id)
        assert build.dataset_label_id == label_id
        
        audit_log = BuildAuditLog.query.filter_by(build_id=build_id).first()
        assert audit_log is not None
        assert audit_log.admin_user_id == admin_id
        assert audit_log.field_changed == 'dataset_label'


def test_set_build_dataset_label_remove(client, app, admin_user):
    """Test removing dataset label from a build."""
    submission_id, build_id, screenshot_id = create_test_submission_with_build(app)
    label_id, label_name = create_test_dataset_label(app, "Test Label")
    
    # Set initial label
    with app.app_context():
        build = Build.query.get(build_id)
        build.dataset_label_id = label_id
        db.session.commit()
        
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post(f'/admin/api/builds/{build_id}/set-label', 
                          json={'label_id': None})
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert data['success'] is True
    assert data['label_id'] is None
    
    # Verify label was removed
    with app.app_context():
        build = Build.query.get(build_id)
        assert build.dataset_label_id is None


def test_update_build_details_success(client, app, admin_user):
    """Test updating build details (platform/type)."""
    submission_id, build_id, screenshot_id = create_test_submission_with_build(app)
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
        admin_id = admin.id
    
    login_admin(client, admin_username, 'password')
    
    response = client.post(f'/admin/api/builds/{build_id}/update-details', 
                          json={'field': 'platform', 'value': 'Mac'})
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert data['success'] is True
    
    # Verify build was updated and audit log created
    with app.app_context():
        build = Build.query.get(build_id)
        assert build.platform == 'Mac'
        
        audit_log = BuildAuditLog.query.filter_by(
            build_id=build_id, 
            field_changed='platform'
        ).first()
        assert audit_log is not None
        assert audit_log.admin_user_id == admin_id
        assert audit_log.old_value == 'PC'
        assert audit_log.new_value == 'Mac'


def test_update_build_details_invalid_field(client, app, admin_user):
    """Test updating build details with invalid field."""
    submission_id, build_id, screenshot_id = create_test_submission_with_build(app)
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post(f'/admin/api/builds/{build_id}/update-details', 
                          json={'field': 'invalid_field', 'value': 'test'})
    assert response.status_code == 400
    
    data = json.loads(response.data)
    assert 'error' in data
    assert 'Invalid field' in data['error']


def test_get_build_audit_log(client, app, admin_user):
    """Test getting build audit log."""
    submission_id, build_id, screenshot_id = create_test_submission_with_build(app)
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
        admin_id = admin.id
        
        # Create audit log entry
        audit_log = BuildAuditLog(
            build_id=build_id,
            admin_user_id=admin_id,
            field_changed='platform',
            old_value='PC',
            new_value='Mac'
        )
        db.session.add(audit_log)
        db.session.commit()
    
    login_admin(client, admin_username, 'password')
    
    response = client.get(f'/admin/api/builds/{build_id}/audit-log')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert isinstance(data, list)
    if data:  # If there's data, verify structure
        assert 'field_changed' in data[0]
        assert 'old_value' in data[0]
        assert 'new_value' in data[0]


# ===== ADMIN EMAIL/LINK LOG TESTS =====

def test_admin_email_log_requires_login(client, app):
    """Test admin email log endpoint requires authentication."""
    response = client.get('/admin/api/email_log/test-log-id')
    assert response.status_code == 403  # Forbidden


def test_admin_email_log_authenticated(client, app, admin_user):
    """Test admin email log endpoint with authentication."""
    # Create test email log
    submission_id, build_id, screenshot_id = create_test_submission_with_build(app)
    
    with app.app_context():
        email_log = EmailLog(
            submission_id=submission_id,
            from_address='test@example.com',
            subject='Test Subject',
            body_text='Test body'
        )
        db.session.add(email_log)
        db.session.commit()
        log_id = email_log.id
        
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.get(f'/admin/api/email_log/{log_id}')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert 'from' in data  # API returns 'from' not 'from_address'
    assert 'subject' in data


def test_admin_link_log_authenticated(client, app, admin_user):
    """Test admin link log endpoint with authentication."""
    # Create test link log
    submission_id, build_id, screenshot_id = create_test_submission_with_build(app)
    
    with app.app_context():
        link_log = LinkLog(
            submission_id=submission_id,
            ip_address='127.0.0.1',
            user_agent='Test Agent',
            token_used='test_token'
        )
        db.session.add(link_log)
        db.session.commit()
        log_id = link_log.id
        
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.get(f'/admin/api/link_log/{log_id}')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert 'ip_address' in data
    assert 'user_agent' in data


# ===== ADMIN RESEND CONSENT EMAIL TESTS =====

@patch('sister_website.app.send_consent_email')
def test_resend_consent_email_success(mock_send_consent, client, app, admin_user):
    """Test resending consent email."""
    submission_id, build_id, screenshot_id = create_test_submission_with_build(app, accepted=False)
    mock_send_consent.return_value = True
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post(f'/admin/api/resend-consent/{submission_id}')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert data['status'] == 'success'  # API returns 'status' not 'success'
    mock_send_consent.assert_called_once()


@patch('sister_website.app.send_consent_email')
def test_resend_consent_email_failure(mock_send_consent, client, app, admin_user):
    """Test resending consent email failure."""
    submission_id, build_id, screenshot_id = create_test_submission_with_build(app, accepted=False)
    mock_send_consent.return_value = False
    
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post(f'/admin/api/resend-consent/{submission_id}')
    assert response.status_code == 500
    
    data = json.loads(response.data)
    assert 'error' in data  # API returns 'error' field on failure
    mock_send_consent.assert_called_once()


def test_resend_consent_email_not_found(client, app, admin_user):
    """Test resending consent email for non-existent submission."""
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.post('/admin/api/resend-consent/nonexistent-id')
    assert response.status_code == 404


# ===== ADMIN SCREENSHOT THUMBNAIL TESTS =====

def test_admin_screenshot_thumbnail_success(client, app, admin_user):
    """Test admin screenshot thumbnail endpoint."""
    submission_id, build_id, screenshot_id = create_test_submission_with_build(app)
    
    # Add thumbnail data
    with app.app_context():
        screenshot = Screenshot.query.get(screenshot_id)
        screenshot.thumbnail_data = b'fake_thumbnail_data'
        db.session.commit()
        
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.get(f'/admin/screenshot/{screenshot_id}/thumbnail')
    assert response.status_code == 200
    assert response.headers['Content-Type'] in ['image/png', 'image/jpeg']  # Accept either format


def test_admin_screenshot_thumbnail_not_found(client, app, admin_user):
    """Test admin screenshot thumbnail for non-existent screenshot."""
    with app.app_context():
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    login_admin(client, admin_username, 'password')
    
    response = client.get('/admin/screenshot/999999/thumbnail')
    assert response.status_code == 404


# ===== AUTHORIZATION TESTS =====

def test_admin_routes_require_admin_auth(client, app):
    """Test that all admin routes require admin authentication."""
    admin_routes = [
        '/admin',
        '/admin/users',
        '/admin/submissions',
        '/admin/dataset-labels',
        '/admin/dataset-manager'
    ]
    
    for route in admin_routes:
        response = client.get(route)
        assert response.status_code == 302, f"Route {route} should redirect to login"


def test_admin_api_routes_require_admin_auth(client, app):
    """Test that all admin API routes require admin authentication."""
    api_routes = [
        '/admin/api/submissions',
        '/admin/api/screenshot_info/1',
        '/admin/api/email_log/test-id',
        '/admin/api/link_log/test-id'
    ]
    
    for route in api_routes:
        response = client.get(route)
        assert response.status_code == 403, f"API route {route} should return 403 Forbidden"


# ===== NORMAL USER MANAGEMENT TESTS =====

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
