import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from sister_website.models import User, Submission, Build, Screenshot, AcceptanceState, db
from sister_website.email_utils import (
    send_consent_email,
    send_reply_confirmation_email, 
    send_verification_email,
    send_password_reset_email
)


def create_test_submission_with_builds(app, email="test@example.com"):
    """Helper to create a submission with builds for testing."""
    with app.app_context():
        submission = Submission(
            email=email,
            acceptance_token='test_token_123',
            acceptance_state=AcceptanceState.PENDING
        )
        
        build1 = Build(submission=submission, platform='PC', type='space')
        build2 = Build(submission=submission, platform='Mobile', type='ground')
        
        # Create some test screenshot data
        screenshot_data = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100  # Minimal PNG header + data
        
        screenshot1 = Screenshot(
            build=build1,
            filename='test1.png',
            md5sum='abc123',
            data=screenshot_data
        )
        screenshot2 = Screenshot(
            build=build2, 
            filename='test2.png',
            md5sum='def456',
            data=screenshot_data
        )
        
        db.session.add_all([submission, build1, build2, screenshot1, screenshot2])
        db.session.commit()
        
        # Refresh to avoid detached instance issues and eagerly load all relationships
        db.session.refresh(submission)
        # Force load the builds relationship and their screenshots while in session
        for build in submission.builds:
            _ = build.screenshots  # Force load screenshots
        return submission


@patch('sister_website.email_utils.ForwardEmailClient')
@patch('sister_website.email_utils.url_for')
def test_send_consent_email_success(mock_url_for, mock_client_class, app):
    """Test successful consent email sending."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_url_for.return_value = 'http://localhost/accept/token123'
    
    with app.app_context():
        submission = create_test_submission_with_builds(app, email="test@example.com")
        consents = {'agreed_to_license': True}
        result = send_consent_email(
            submission.email,
            submission.builds,
            consents,
            submission.acceptance_token,
            submission.id
        )
        
        assert result is True
        mock_client_class.assert_called_once()
        mock_client.send_email.assert_called_once()


@patch('sister_website.email_utils.ForwardEmailClient')
@patch('sister_website.email_utils.url_for')
def test_send_consent_email_failure(mock_url_for, mock_client_class, app):
    """Test consent email sending failure."""
    mock_client = MagicMock()
    mock_client.send_email.side_effect = Exception("Email sending failed")
    mock_client_class.return_value = mock_client
    mock_url_for.return_value = 'http://localhost/accept/token123'
    
    with app.app_context():
        submission = create_test_submission_with_builds(app, email="test@example.com")
        consents = {'agreed_to_license': True}
        result = send_consent_email(
            submission.email,
            submission.builds,
            consents,
            submission.acceptance_token,
            submission.id
        )
        
        assert result is False


@patch('sister_website.email_utils.ForwardEmailClient')
@patch('sister_website.email_utils.url_for')
def test_send_verification_email_success(mock_url_for, mock_client_class, app):
    """Test successful verification email sending."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_url_for.return_value = 'http://localhost/verify_email/token123'
    
    with app.app_context():
        user_email = 'newuser@example.com'
        token = 'verification_token_123'
        
        result = send_verification_email(user_email, token)
        
        assert result is True
        mock_client_class.assert_called_once()
        mock_client.send_email.assert_called_once()


@patch('sister_website.email_utils.ForwardEmailClient')
@patch('sister_website.email_utils.url_for')
def test_send_verification_email_failure(mock_url_for, mock_client_class, app):
    """Test verification email sending failure."""
    mock_client = MagicMock()
    mock_client.send_email.side_effect = Exception("Email sending failed")
    mock_client_class.return_value = mock_client
    mock_url_for.return_value = 'http://localhost/verify_email/token123'
    
    with app.app_context():
        result = send_verification_email('user@example.com', 'token123')
        assert result is False


@patch('sister_website.email_utils.ForwardEmailClient')
@patch('sister_website.email_utils.url_for')
def test_send_password_reset_email_success(mock_url_for, mock_client_class, app):
    """Test successful password reset email sending."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_url_for.return_value = 'http://localhost/reset-password/token123'
    
    with app.app_context():
        user_email = 'user@example.com'
        token = 'reset_token_123'
        
        result = send_password_reset_email(user_email, token)
        
        assert result is True
        mock_client_class.assert_called_once()
        mock_client.send_email.assert_called_once()


@patch('sister_website.email_utils.ForwardEmailClient')
@patch('sister_website.email_utils.url_for')
def test_send_password_reset_email_failure(mock_url_for, mock_client_class, app):
    """Test password reset email sending failure.""" 
    mock_client = MagicMock()
    mock_client.send_email.side_effect = Exception("Email sending failed")
    mock_client_class.return_value = mock_client
    mock_url_for.return_value = 'http://localhost/reset-password/token123'
    
    with app.app_context():
        result = send_password_reset_email('user@example.com', 'token123')
        assert result is False


@patch('sister_website.email_utils.ForwardEmailClient')
@patch('sister_website.email_utils.url_for')
def test_send_reply_confirmation_email_success(mock_url_for, mock_client_class, app):
    """Test reply confirmation email success."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_url_for.return_value = 'http://localhost/withdraw/token123'
    
    with app.app_context():
        submission = create_test_submission_with_builds(app, email="test@example.com")
        result = send_reply_confirmation_email(
            submission.email,
            submission.id,
            "Accepted",
            "reply@example.com",
            submission.acceptance_token
        )
        
        assert result is True
        mock_client_class.assert_called_once()
        mock_client.send_email.assert_called_once()


@patch('sister_website.email_utils.ForwardEmailClient')
@patch('sister_website.email_utils.url_for')
def test_send_reply_confirmation_email_failure(mock_url_for, mock_client_class, app):
    """Test reply confirmation email sending failure."""
    mock_client = MagicMock()
    mock_client.send_email.side_effect = Exception("Email sending failed")
    mock_client_class.return_value = mock_client
    mock_url_for.return_value = 'http://localhost/withdraw/token123'
    
    with app.app_context():
        submission = create_test_submission_with_builds(app, email="test@example.com")
        result = send_reply_confirmation_email(
            submission.email,
            submission.id,
            "Accepted",
            "reply@example.com"
        )
        
        assert result is False


def test_send_reply_confirmation_email_missing_parameters(app):
    """Test reply confirmation email with missing required parameters."""
    with app.app_context():
        # Missing reply channel address
        result = send_reply_confirmation_email(
            "user@example.com",
            "submission_id",
            "Accepted",
            None  # Missing reply channel
        )
        assert result is False
        
        # Missing sender email
        result = send_reply_confirmation_email(
            None,  # Missing sender email
            "submission_id", 
            "Accepted",
            "reply@example.com"
        )
        assert result is False


@patch('sister_website.email_utils.ForwardEmailClient')
def test_email_missing_api_key(mock_client_class, app, monkeypatch):
    """Test email sending when API key is missing."""
    # Remove the API key environment variable
    monkeypatch.delenv('FORWARD_EMAIL_API_KEY', raising=False)
    
    mock_client_class.side_effect = Exception("Missing API key")
    
    with app.app_context():
        result = send_verification_email('user@example.com', 'token123')
        assert result is False


@patch('sister_website.email_utils.ForwardEmailClient')
@patch('sister_website.email_utils.url_for')
def test_email_network_error(mock_url_for, mock_client_class, app):
    """Test email sending with network error."""
    mock_client = MagicMock()
    mock_client.send_email.side_effect = Exception("Network error")
    mock_client_class.return_value = mock_client
    mock_url_for.return_value = 'http://localhost/verify_email/token123'
    
    with app.app_context():
        result = send_verification_email('user@example.com', 'token123')
        assert result is False


@patch('sister_website.email_utils.ForwardEmailClient')
@patch('sister_website.email_utils.render_template')
@patch('sister_website.email_utils.url_for')
def test_consent_email_template_content(mock_url_for, mock_render, mock_client_class, app):
    """Test that consent email contains required elements."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_render.return_value = "<html>Test email content</html>"
    mock_url_for.return_value = 'http://localhost/accept/token123'
    
    with app.app_context():
        submission = create_test_submission_with_builds(app, email="test@example.com")
        consents = {'agreed_to_license': True}
        result = send_consent_email(
            submission.email,
            submission.builds,
            consents,
            submission.acceptance_token,
            submission.id
        )
        
        assert result is True
        # Verify template was called with correct parameters
        mock_render.assert_called_once()
        call_args = mock_render.call_args
        template_name = call_args[0][0]
        assert 'email_template.html' in template_name
        
        # Verify template context contains required elements
        template_context = call_args[1]
        assert 'builds' in template_context
        assert 'consents' in template_context
        assert 'acceptance_url' in template_context
        assert 'decline_url' in template_context 