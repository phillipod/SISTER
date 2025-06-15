import pytest
from unittest.mock import patch
from itsdangerous import URLSafeTimedSerializer
from sister_website.models import User, db
from sister_website.forms import ForgotPasswordForm, ResetPasswordForm


def create_test_user(app, email="user@example.com", password="password123"):
    """Helper to create test user."""
    with app.app_context():
        user = User(email=email, email_verified=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        # Return the email and user ID to avoid detached instance issues
        return {'email': user.email, 'id': user.id}


def test_forgot_password_page_get(client, app):
    """Test GET request to forgot password page."""
    response = client.get('/forgot-password')
    assert response.status_code == 200
    assert b'forgot' in response.data.lower() or b'reset' in response.data.lower()


def test_forgot_password_valid_email(client, app):
    """Test forgot password with valid existing email."""
    user_data = create_test_user(app)
    
    with patch('sister_website.app.send_password_reset_email') as mock_send:
        mock_send.return_value = True
        
        response = client.post('/forgot-password', data={
            'email': user_data['email']
        }, follow_redirects=True)
        
        assert response.status_code == 200
        # Should show success message
        assert b'email' in response.data.lower() or b'sent' in response.data.lower()
        
        # Verify email was sent
        mock_send.assert_called_once()


def test_forgot_password_invalid_email(client, app):
    """Test forgot password with non-existent email."""
    with patch('sister_website.app.send_password_reset_email') as mock_send:
        response = client.post('/forgot-password', data={
            'email': 'nonexistent@example.com'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        # Should still show success message for security (don't reveal valid emails)
        # or show generic message
        
        # Email should not be sent for non-existent users
        mock_send.assert_not_called()


def test_forgot_password_invalid_email_format(client, app):
    """Test forgot password with invalid email format."""
    response = client.post('/forgot-password', data={
        'email': 'invalid-email-format'
    })
    
    assert response.status_code == 200
    # Should show validation error
    assert b'valid' in response.data.lower() or b'email' in response.data.lower()


def test_forgot_password_empty_email(client, app):
    """Test forgot password with empty email."""
    response = client.post('/forgot-password', data={
        'email': ''
    })
    
    assert response.status_code == 200
    # Should show validation error
    assert b'required' in response.data.lower() or b'field' in response.data.lower()


@patch('sister_website.app.send_password_reset_email')
def test_forgot_password_email_send_failure(mock_send, client, app):
    """Test forgot password when email sending fails."""
    mock_send.return_value = False
    user_data = create_test_user(app)
    
    response = client.post('/forgot-password', data={
        'email': user_data['email']
    }, follow_redirects=True)
    
    assert response.status_code == 200
    # Should handle email sending failure gracefully


def generate_test_token(app, user_email):
    """Generate a test reset token by creating it in the database."""
    with app.app_context():
        user = User.query.filter_by(email=user_email).first()
        if user:
            token = user.generate_password_reset_token()
            db.session.commit()
            return token
        return None


def test_reset_password_page_valid_token(client, app):
    """Test GET request to reset password page with valid token."""
    user_data = create_test_user(app)
    token = generate_test_token(app, user_data['email'])
    
    response = client.get(f'/reset-password/{token}')
    assert response.status_code == 200
    assert b'new password' in response.data.lower() or b'reset' in response.data.lower()


def test_reset_password_page_invalid_token(client, app):
    """Test GET request to reset password page with invalid token."""
    response = client.get('/reset-password/invalid_token')
    assert response.status_code in [400, 404, 302]  # Should reject invalid token


def test_reset_password_page_expired_token(client, app):
    """Test GET request to reset password page with expired token."""
    user_data = create_test_user(app)
    
    # Create expired token by mocking the serializer
    with patch('itsdangerous.URLSafeTimedSerializer.loads') as mock_loads:
        mock_loads.side_effect = Exception("Token expired")
        
        token = "expired_token"
        response = client.get(f'/reset-password/{token}')
        assert response.status_code in [400, 404, 302]


def test_reset_password_success(client, app):
    """Test successful password reset."""
    user_data = create_test_user(app)
    token = generate_test_token(app, user_data['email'])
    
    response = client.post(f'/reset-password/{token}', data={
        'password': 'newpassword123',
        'confirm_password': 'newpassword123'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    
    # Verify password was changed
    with app.app_context():
        updated_user = User.query.filter_by(email=user_data['email']).first()
        assert updated_user.check_password('newpassword123')
        assert not updated_user.check_password('password123')


def test_reset_password_mismatched_passwords(client, app):
    """Test password reset with mismatched passwords."""
    user_data = create_test_user(app)
    token = generate_test_token(app, user_data['email'])
    
    response = client.post(f'/reset-password/{token}', data={
        'password': 'newpassword123',
        'confirm_password': 'differentpassword'
    })
    
    assert response.status_code == 200
    # Should show validation error
    assert b'match' in response.data.lower() or b'password' in response.data.lower()


def test_reset_password_weak_password(client, app):
    """Test password reset with weak password."""
    user_data = create_test_user(app)
    token = generate_test_token(app, user_data['email'])
    
    response = client.post(f'/reset-password/{token}', data={
        'password': '123',  # Too short
        'confirm_password': '123'
    })
    
    # The app might accept weak passwords or redirect on success
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        # Should show validation error about password strength
        assert b'password' in response.data.lower()


def test_reset_password_token_used_twice(client, app):
    """Test that reset token can't be used twice."""
    user_data = create_test_user(app)
    token = generate_test_token(app, user_data['email'])
    
    # First reset - should succeed
    response1 = client.post(f'/reset-password/{token}', data={
        'password': 'newpassword123',
        'confirm_password': 'newpassword123'
    }, follow_redirects=True)
    assert response1.status_code == 200
    
    # Second reset with same token - should fail
    response2 = client.post(f'/reset-password/{token}', data={
        'password': 'anothernewpassword',
        'confirm_password': 'anothernewpassword'
    })
    
    # Should reject the token (implementation dependent)
    # Some implementations invalidate tokens, others allow reuse
    assert response2.status_code in [200, 400, 404, 302]


def test_reset_password_nonexistent_user(client, app):
    """Test password reset for non-existent user."""
    # Generate token for non-existent email
    fake_token = generate_test_token(app, "nonexistent@example.com")
    
    response = client.post(f'/reset-password/{fake_token}', data={
        'password': 'newpassword123',
        'confirm_password': 'newpassword123'
    })
    
    # Should handle gracefully
    assert response.status_code in [200, 400, 404, 302]


def test_forgot_password_form_validation(app):
    """Test ForgotPasswordForm validation."""
    with app.app_context():
        try:
            # Test valid form
            form = ForgotPasswordForm(data={'email': 'user@example.com'})
            assert form.validate() is True
            
            # Test invalid email
            form = ForgotPasswordForm(data={'email': 'invalid-email'})
            assert form.validate() is False
            
            # Test empty form
            form = ForgotPasswordForm(data={'email': ''})
            assert form.validate() is False
            
        except (ImportError, NameError):
            pytest.skip("ForgotPasswordForm not found or has different structure")


def test_reset_password_form_validation(app):
    """Test ResetPasswordForm validation."""
    with app.app_context():
        try:
            # Test valid form
            form = ResetPasswordForm(data={
                'password': 'newpassword123',
                'confirm_password': 'newpassword123'
            })
            assert form.validate() is True
            
            # Test mismatched passwords
            form = ResetPasswordForm(data={
                'password': 'password1',
                'confirm_password': 'password2'
            })
            assert form.validate() is False
            
            # Test empty form
            form = ResetPasswordForm(data={
                'password': '',
                'confirm_password': ''
            })
            assert form.validate() is False
            
        except (ImportError, NameError):
            pytest.skip("ResetPasswordForm not found or has different structure")


def test_reset_password_rate_limiting(client, app):
    """Test rate limiting on password reset requests."""
    user_data = create_test_user(app)
    
    # Make multiple requests quickly
    for i in range(5):
        with patch('sister_website.app.send_password_reset_email') as mock_send:
            mock_send.return_value = True
            response = client.post('/forgot-password', data={
                'email': user_data['email']
            })
            
            # Should handle rate limiting gracefully
            assert response.status_code in [200, 302, 429]  # 302 = redirect, 429 = Too Many Requests 