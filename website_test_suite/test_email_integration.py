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
        return submission


@patch('sister_website.email_utils.requests.post')
def test_send_consent_email_success(mock_post, app):
    """Test successful consent email sending."""
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {'message': 'Queued'}
    
    submission = create_test_submission_with_builds(app)
    
    with app.app_context():
        consents = {'agreed_to_license': True}
        result = send_consent_email(
            submission.email,
            submission.builds,
            consents,
            submission.acceptance_token,
            submission.id
        )
        
        assert result is True
        mock_post.assert_called_once()
        
        # Verify the email content
        call_args = mock_post.call_args
        json_data = call_args[1]['json']
        
        assert json_data['to'] == submission.email
        assert json_data['subject'] == 'Consent Required: SISTER Screenshot Submission'
        assert submission.acceptance_token in json_data['html']
        assert 'PC' in json_data['html']  # Platform should be mentioned
        assert 'Mobile' in json_data['html']  # Platform should be mentioned


@patch('sister_website.email_utils.requests.post')
def test_send_consent_email_failure(mock_post, app):
    """Test consent email sending failure."""
    mock_post.return_value.status_code = 400
    mock_post.return_value.text = 'Bad Request'
    
    submission = create_test_submission_with_builds(app)
    
    with app.app_context():
        consents = {'agreed_to_license': True}
        result = send_consent_email(
            submission.email,
            submission.builds,
            consents,
            submission.acceptance_token,
            submission.id
        )
        
        assert result is False


@patch('sister_website.email_utils.requests.post')
def test_send_verification_email_success(mock_post, app):
    """Test successful verification email sending."""
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {'message': 'Queued'}
    
    with app.app_context():
        user = User(email='newuser@example.com')
        token = 'verification_token_123'
        
        result = send_verification_email(user.email, token)
        
        assert result is True
        mock_post.assert_called_once()
        
        # Verify the email content
        call_args = mock_post.call_args
        json_data = call_args[1]['json']
        
        assert json_data['to'] == user.email
        assert json_data['subject'] == 'Verify Your Email Address - SISTER'
        assert token in json_data['html']


@patch('sister_website.email_utils.requests.post')
def test_send_verification_email_failure(mock_post, app):
    """Test verification email sending failure."""
    mock_post.return_value.status_code = 500
    mock_post.return_value.text = 'Internal Server Error'
    
    with app.app_context():
        result = send_verification_email('user@example.com', 'token123')
        assert result is False


@patch('sister_website.email_utils.requests.post')
def test_send_password_reset_email_success(mock_post, app):
    """Test successful password reset email sending."""
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {'message': 'Queued'}
    
    with app.app_context():
        user = User(email='user@example.com')
        token = 'reset_token_123'
        
        result = send_password_reset_email(user.email, token)
        
        assert result is True
        mock_post.assert_called_once()
        
        # Verify the email content
        call_args = mock_post.call_args
        json_data = call_args[1]['json']
        
        assert json_data['to'] == user.email
        assert json_data['subject'] == 'Password Reset Request - SISTER'
        assert token in json_data['html']


@patch('sister_website.email_utils.requests.post')
def test_send_password_reset_email_failure(mock_post, app):
    """Test password reset email sending failure.""" 
    mock_post.return_value.status_code = 400
    
    with app.app_context():
        result = send_password_reset_email('user@example.com', 'token123')
        assert result is False


@patch('sister_website.email_utils.requests.post')
def test_send_reply_confirmation_email_accepted(mock_post, app):
    """Test reply confirmation email for acceptance."""
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {'message': 'Queued'}
    
    submission = create_test_submission_with_builds(app)
    
    with app.app_context():
        submission.acceptance_state = AcceptanceState.ACCEPTED
        submission.accepted_at = datetime.utcnow()
        db.session.commit()
        
        result = send_reply_confirmation_email(
            submission.email,
            submission.id,
            submission.acceptance_state,
            "Thank you for accepting!"
        )
        
        assert result is True
        mock_post.assert_called_once()
        
        # Verify the email content
        call_args = mock_post.call_args
        json_data = call_args[1]['json']
        
        assert json_data['to'] == submission.email
        assert json_data['subject'] == 'Submission Accepted - SISTER'
        assert 'accepted' in json_data['html'].lower()


@patch('sister_website.email_utils.requests.post')
def test_send_reply_confirmation_email_declined(mock_post, app):
    """Test reply confirmation email for decline."""
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {'message': 'Queued'}
    
    submission = create_test_submission_with_builds(app)
    
    with app.app_context():
        submission.acceptance_state = AcceptanceState.DECLINED
        db.session.commit()
        
        result = send_reply_confirmation_email(
            submission.email,
            submission.id,
            submission.acceptance_state,
            "Thank you for your response."
        )
        
        assert result is True
        mock_post.assert_called_once()
        
        # Verify the email content
        call_args = mock_post.call_args
        json_data = call_args[1]['json']
        
        assert json_data['to'] == submission.email
        assert json_data['subject'] == 'Submission Declined - SISTER'
        assert 'declined' in json_data['html'].lower()


@patch('sister_website.email_utils.requests.post')
def test_send_reply_confirmation_email_failure(mock_post, app):
    """Test reply confirmation email sending failure."""
    mock_post.return_value.status_code = 500
    
    submission = create_test_submission_with_builds(app)
    
    with app.app_context():
        result = send_reply_confirmation_email(
            submission.email,
            submission.id,
            AcceptanceState.ACCEPTED,
            "Test message"
        )
        
        assert result is False


@patch('sister_website.email_utils.requests.post')
def test_email_missing_api_key(mock_post, app, monkeypatch):
    """Test email sending when API key is missing."""
    # Remove the API key environment variable
    monkeypatch.delenv('FORWARDEMAIL_API_KEY', raising=False)
    
    with app.app_context():
        result = send_verification_email('user@example.com', 'token123')
        assert result is False
        mock_post.assert_not_called()


@patch('sister_website.email_utils.requests.post')
def test_email_network_error(mock_post, app):
    """Test email sending with network error."""
    mock_post.side_effect = Exception("Network error")
    
    with app.app_context():
        result = send_verification_email('user@example.com', 'token123')
        assert result is False


def test_consent_email_template_content(app):
    """Test that consent email contains required elements."""
    submission = create_test_submission_with_builds(app)
    
    with app.app_context():
        # Import the template rendering function
        from sister_website.email_utils import send_consent_email
        
        # We'll mock the requests.post but capture the template content
        with patch('sister_website.email_utils.requests.post') as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {'message': 'Queued'}
            
            consents = {'agreed_to_license': True}
            send_consent_email(
                submission.email,
                submission.builds,
                consents,
                submission.acceptance_token,
                submission.id
            )
            
            # Get the HTML content from the mock call
            call_args = mock_post.call_args
            html_content = call_args[1]['json']['html']
            
            # Verify required elements are present
            assert 'SISTER' in html_content
            assert 'consent' in html_content.lower()
            assert submission.acceptance_token in html_content
            assert 'accept' in html_content.lower()
            assert 'decline' in html_content.lower()
            assert 'PC' in html_content  # Platform info
            assert 'Mobile' in html_content  # Platform info 