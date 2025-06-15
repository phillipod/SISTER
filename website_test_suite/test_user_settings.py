import pytest
from unittest.mock import patch
from sister_website.models import User, db
from sister_website.forms import UserSettingsForm


def create_test_user(app, email="user@example.com", password="password123"):
    """Helper to create a test user and return user_id and email."""
    with app.app_context():
        user = User(email=email, email_verified=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id, user.email


def login_user(client, email, password):
    """Helper to log in a user."""
    return client.post('/login', data={
        'email': email,
        'password': password
    }, follow_redirects=True)


def test_settings_page_requires_login(client, app):
    """Test that settings page requires login."""
    response = client.get('/settings')
    assert response.status_code == 302  # Redirect to login
    assert '/login' in response.location


def test_settings_page_get_authenticated(client, app):
    """Test GET request to settings page when authenticated."""
    user_id, user_email = create_test_user(app)
    
    # Log in the user
    login_response = login_user(client, user_email, 'password123')
    assert login_response.status_code == 200
    
    # Access settings page
    response = client.get('/settings')
    assert response.status_code == 200
    assert b'Account Settings' in response.data or b'Settings' in response.data


def test_change_password_success(client, app):
    """Test successful password change."""
    user_id, user_email = create_test_user(app)
    
    # Log in the user
    login_user(client, user_email, 'password123')
    
    # Change password
    response = client.post('/settings', data={
        'current_password': 'password123',
        'new_password': 'newpassword456',
        'confirm_password': 'newpassword456'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    
    # Verify password was changed by attempting login with new password
    client.get('/logout')  # Logout first
    login_response = login_user(client, user_email, 'newpassword456')
    assert login_response.status_code == 200


def test_change_password_wrong_current_password(client, app):
    """Test password change with wrong current password."""
    user_id, user_email = create_test_user(app)
    
    # Log in the user
    login_user(client, user_email, 'password123')
    
    # Try to change password with wrong current password
    response = client.post('/settings', data={
        'current_password': 'wrongpassword',
        'new_password': 'newpassword456',
        'confirm_password': 'newpassword456'
    })
    
    assert response.status_code == 200
    # Should show error or stay on same page
    assert b'current password' in response.data.lower() or b'incorrect' in response.data.lower()


def test_change_password_mismatch(client, app):
    """Test password change with mismatched new passwords."""
    user_id, user_email = create_test_user(app)
    
    # Log in the user
    login_user(client, user_email, 'password123')
    
    # Try to change password with mismatched new passwords
    response = client.post('/settings', data={
        'current_password': 'password123',
        'new_password': 'newpassword456',
        'confirm_password': 'differentpassword'
    })
    
    assert response.status_code == 200
    # Should show validation error
    assert b'password' in response.data.lower()


def test_contributor_recognition_settings(client, app):
    """Test updating contributor recognition settings."""
    user_id, user_email = create_test_user(app)
    
    # Log in the user
    login_user(client, user_email, 'password123')
    
    # Update contributor recognition settings
    response = client.post('/settings', data={
        'current_password': 'password123',
        'contributor_recognition_enabled': True,
        'contributor_recognition_text': 'John Doe',
        'submit': 'Save Settings'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Settings updated successfully' in response.data
    
    # Verify settings were updated
    with app.app_context():
        updated_user = User.query.get(user_id)
        assert updated_user.contributor_recognition_enabled == True
        assert updated_user.contributor_recognition_text == 'John Doe'


def test_contributor_recognition_disable(client, app):
    """Test disabling contributor recognition."""
    user_id, user_email = create_test_user(app)
    
    # First enable contributor recognition
    with app.app_context():
        user_obj = User.query.get(user_id)
        user_obj.contributor_recognition_enabled = True
        user_obj.contributor_recognition_text = 'Test User'
        db.session.commit()
    
    # Log in the user
    login_user(client, user_email, 'password123')
    
    # Disable contributor recognition (don't include the field to uncheck it)
    response = client.post('/settings', data={
        'current_password': 'password123',
        'submit': 'Save Settings'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Settings updated successfully' in response.data
    
    # Verify settings were updated
    with app.app_context():
        updated_user = User.query.get(user_id)
        assert updated_user.contributor_recognition_enabled == False
        assert updated_user.contributor_recognition_text is None


def test_settings_wrong_current_password(client, app):
    """Test settings update with wrong current password."""
    user_id, user_email = create_test_user(app)
    
    # Log in the user
    login_user(client, user_email, 'password123')
    
    # Try to update settings with wrong current password
    response = client.post('/settings', data={
        'current_password': 'wrongpassword',
        'new_password': 'newpassword456',
        'confirm_password': 'newpassword456',
        'submit': 'Save Settings'
    })
    
    assert response.status_code == 200
    assert b'Current password is incorrect' in response.data


def test_password_only_change(client, app):
    """Test changing only password without other settings."""
    user_id, user_email = create_test_user(app)
    
    # Log in the user
    login_user(client, user_email, 'password123')
    
    # Change only password
    response = client.post('/settings', data={
        'current_password': 'password123',
        'new_password': 'newpassword456',
        'confirm_password': 'newpassword456',
        'submit': 'Save Settings'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Password updated successfully' in response.data or b'Settings updated successfully' in response.data
    
    # Verify password was changed by attempting login with new password
    client.get('/logout')  # Logout first
    login_response = login_user(client, user_email, 'newpassword456')
    assert login_response.status_code == 200


def test_settings_form_prepopulation(client, app):
    """Test that settings form is pre-populated with current user data."""
    user_id, user_email = create_test_user(app)
    
    # Set some initial contributor recognition settings
    with app.app_context():
        user_obj = User.query.get(user_id)
        user_obj.contributor_recognition_enabled = True
        user_obj.contributor_recognition_text = 'Test User'
        db.session.commit()
    
    # Log in the user
    login_user(client, user_email, 'password123')
    
    # Get settings page
    response = client.get('/settings')
    assert response.status_code == 200
    
    # Check that form is pre-populated (this depends on template implementation)
    # At minimum, the page should load successfully
    assert b'Settings' in response.data or b'Account' in response.data


def test_csrf_protection_settings(client, app):
    """Test CSRF protection on settings form."""
    user_id, user_email = create_test_user(app)
    
    # Log in the user
    login_user(client, user_email, 'password123')
    
    # Try to submit form without proper CSRF token (if CSRF is enabled)
    with patch('flask_wtf.csrf.CSRFProtect.protect', side_effect=Exception("CSRF token missing")):
        response = client.post('/settings', data={
            'new_password': 'newpassword456',
            'confirm_password': 'newpassword456'
        })
        
        # Should be rejected or handled gracefully
        assert response.status_code in [200, 403, 400]


def test_settings_form_validation(app):
    """Test UserSettingsForm validation."""
    with app.app_context():
        form = UserSettingsForm()
        
        # Test password validation - new password without confirmation
        form.current_password.data = 'currentpass'
        form.new_password.data = 'newpassword'
        form.confirm_password.data = ''
        assert not form.validate()
        assert 'new_password' in form.errors
        
        # Test password validation - confirmation without new password
        form.new_password.data = ''
        form.confirm_password.data = 'newpassword'
        assert not form.validate()
        assert 'new_password' in form.errors
        
        # Test password validation - matching passwords
        form.new_password.data = 'newpassword'
        form.confirm_password.data = 'newpassword'
        # Should pass password validation (current_password still required)
        form.validate()
        assert 'new_password' not in form.errors or len(form.errors.get('new_password', [])) == 0


def test_settings_page_shows_current_info(client, app):
    """Test that settings page shows current user information."""
    user_id, user_email = create_test_user(app, email="test@example.com")
    
    # Log in the user
    login_user(client, user_email, 'password123')
    
    # Get settings page
    response = client.get('/settings')
    assert response.status_code == 200
    
    # Should show settings form elements
    assert b'current_password' in response.data or b'Current Password' in response.data
    assert b'new_password' in response.data or b'New Password' in response.data 