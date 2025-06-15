import pytest
import json
import hmac
import hashlib
from unittest.mock import patch
from datetime import datetime
from sister_website.models import Submission, EmailLog, AcceptanceState, db
from sister_website.email_utils import verify_webhook_signature


def create_test_webhook_payload():
    """Create a test webhook payload from ForwardEmail."""
    return {
        "messageId": "<test-message-id@example.com>",
        "from": "user@example.com", 
        "to": "screenshots@sister.example.com",
        "subject": "RE: Consent Required: SISTER Screenshot Submission",
        "text": "I accept the terms and conditions.",
        "html": "<p>I accept the terms and conditions.</p>",
        "headers": {
            "message-id": "<test-message-id@example.com>",
            "from": "user@example.com",
            "to": "screenshots@sister.example.com",
            "subject": "RE: Consent Required: SISTER Screenshot Submission",
            "date": "Mon, 15 Jun 2025 10:00:00 +0000"
        },
        "date": "2025-06-15T10:00:00.000Z",
        "attachments": []
    }


def create_webhook_signature(payload_str, secret):
    """Create a valid webhook signature."""
    return hmac.new(
        secret.encode('utf-8'),
        payload_str.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


def test_webhook_signature_validation_valid():
    """Test webhook signature validation with valid signature."""
    payload = {"test": "data"}
    payload_str = json.dumps(payload, separators=(',', ':'))
    secret = "test_secret_key"
    signature = create_webhook_signature(payload_str, secret)
    
    with patch('os.getenv', return_value=secret):
        result = verify_webhook_signature(payload_str, signature)
        assert result is True


def test_webhook_signature_validation_invalid():
    """Test webhook signature validation with invalid signature."""
    payload = {"test": "data"}
    payload_str = json.dumps(payload, separators=(',', ':'))
    secret = "test_secret_key"
    wrong_signature = "invalid_signature"
    
    with patch('os.getenv', return_value=secret):
        result = verify_webhook_signature(payload_str, wrong_signature)
        assert result is False


def test_webhook_signature_validation_missing_secret():
    """Test webhook signature validation when secret is missing."""
    payload_str = '{"test": "data"}'
    signature = "some_signature"
    
    with patch('os.getenv', return_value=None):
        result = verify_webhook_signature(payload_str, signature)
        assert result is False


def test_webhook_email_route_success(client, app):
    """Test successful webhook email processing."""
    # Create a test submission
    with app.app_context():
        submission = Submission(
            email='user@example.com',
            acceptance_token='test_token_123',
            acceptance_state=AcceptanceState.PENDING
        )
        db.session.add(submission)
        db.session.commit()
        submission_id = submission.id
    
    # Create webhook payload
    payload = create_test_webhook_payload()
    payload['text'] = f"ACCEPT {submission.acceptance_token}\n\nI agree to the terms."
    payload_str = json.dumps(payload, separators=(',', ':'))
    
    secret = "test_webhook_secret"
    signature = create_webhook_signature(payload_str, secret)
    
    with patch('os.getenv', return_value=secret):
        with patch('sister_website.app.get_forwardemail_ips_cached', return_value=['127.0.0.1']):
            response = client.post(
                '/webhook/email',
                data=payload_str,
                content_type='application/json',
                headers={'X-Webhook-Signature': signature},
                environ_base={'REMOTE_ADDR': '127.0.0.1'}
            )
    
    assert response.status_code == 200
    
    # Verify submission was accepted
    with app.app_context():
        updated_submission = Submission.query.get(submission_id)
        assert updated_submission.acceptance_state == AcceptanceState.ACCEPTED
        assert updated_submission.acceptance_method == 'email'
        
        # Verify email log was created
        email_log = EmailLog.query.filter_by(submission_id=submission_id).first()
        assert email_log is not None
        assert email_log.from_address == 'user@example.com'
        assert email_log.subject == payload['subject']


def test_webhook_email_route_decline(client, app):
    """Test webhook email processing for decline."""
    # Create a test submission
    with app.app_context():
        submission = Submission(
            email='user@example.com',
            acceptance_token='test_token_456',
            acceptance_state=AcceptanceState.PENDING
        )
        db.session.add(submission)
        db.session.commit()
        submission_id = submission.id
    
    # Create webhook payload with decline
    payload = create_test_webhook_payload()
    payload['text'] = f"DECLINE {submission.acceptance_token}\n\nI do not agree."
    payload_str = json.dumps(payload, separators=(',', ':'))
    
    secret = "test_webhook_secret"
    signature = create_webhook_signature(payload_str, secret)
    
    with patch('os.getenv', return_value=secret):
        with patch('sister_website.app.get_forwardemail_ips_cached', return_value=['127.0.0.1']):
            response = client.post(
                '/webhook/email',
                data=payload_str,
                content_type='application/json',
                headers={'X-Webhook-Signature': signature},
                environ_base={'REMOTE_ADDR': '127.0.0.1'}
            )
    
    assert response.status_code == 200
    
    # Verify submission was declined
    with app.app_context():
        updated_submission = Submission.query.get(submission_id)
        assert updated_submission.acceptance_state == AcceptanceState.DECLINED
        assert updated_submission.acceptance_method == 'email'


def test_webhook_email_route_invalid_signature(client, app):
    """Test webhook email processing with invalid signature."""
    payload = create_test_webhook_payload()
    payload_str = json.dumps(payload, separators=(',', ':'))
    invalid_signature = "invalid_signature"
    
    secret = "test_webhook_secret"
    
    with patch('os.getenv', return_value=secret):
        with patch('sister_website.app.get_forwardemail_ips_cached', return_value=['127.0.0.1']):
            response = client.post(
                '/webhook/email',
                data=payload_str,
                content_type='application/json',
                headers={'X-Webhook-Signature': invalid_signature},
                environ_base={'REMOTE_ADDR': '127.0.0.1'}
            )
    
    assert response.status_code == 403


def test_webhook_email_route_unauthorized_ip(client, app):
    """Test webhook email processing from unauthorized IP."""
    payload = create_test_webhook_payload()
    payload_str = json.dumps(payload, separators=(',', ':'))
    
    secret = "test_webhook_secret"
    signature = create_webhook_signature(payload_str, secret)
    
    with patch('os.getenv', return_value=secret):
        with patch('sister_website.app.get_forwardemail_ips_cached', return_value=['1.2.3.4']):  # Different IP
            response = client.post(
                '/webhook/email',
                data=payload_str,
                content_type='application/json',
                headers={'X-Webhook-Signature': signature},
                environ_base={'REMOTE_ADDR': '127.0.0.1'}  # Unauthorized IP
            )
    
    assert response.status_code == 403


def test_webhook_email_route_no_token_found(client, app):
    """Test webhook email processing when no valid token is found."""
    payload = create_test_webhook_payload()
    payload['text'] = "ACCEPT invalid_token_123\n\nI agree to the terms."
    payload_str = json.dumps(payload, separators=(',', ':'))
    
    secret = "test_webhook_secret"
    signature = create_webhook_signature(payload_str, secret)
    
    with patch('os.getenv', return_value=secret):
        with patch('sister_website.app.get_forwardemail_ips_cached', return_value=['127.0.0.1']):
            response = client.post(
                '/webhook/email',
                data=payload_str,
                content_type='application/json',
                headers={'X-Webhook-Signature': signature},
                environ_base={'REMOTE_ADDR': '127.0.0.1'}
            )
    
    # Should still return 200 but no submission should be updated
    assert response.status_code == 200


def test_webhook_email_route_already_processed(client, app):
    """Test webhook email processing for already processed submission."""
    # Create a test submission that's already accepted
    with app.app_context():
        submission = Submission(
            email='user@example.com',
            acceptance_token='test_token_789',
            acceptance_state=AcceptanceState.ACCEPTED,  # Already accepted
            accepted_at=datetime.utcnow(),
            acceptance_method='link'
        )
        db.session.add(submission)
        db.session.commit()
    
    # Try to accept again via email
    payload = create_test_webhook_payload()
    payload['text'] = f"ACCEPT {submission.acceptance_token}\n\nI agree to the terms."
    payload_str = json.dumps(payload, separators=(',', ':'))
    
    secret = "test_webhook_secret"
    signature = create_webhook_signature(payload_str, secret)
    
    with patch('os.getenv', return_value=secret):
        with patch('sister_website.app.get_forwardemail_ips_cached', return_value=['127.0.0.1']):
            response = client.post(
                '/webhook/email',
                data=payload_str,
                content_type='application/json',
                headers={'X-Webhook-Signature': signature},
                environ_base={'REMOTE_ADDR': '127.0.0.1'}
            )
    
    assert response.status_code == 200
    
    # Verify submission state didn't change (still accepted via link)
    with app.app_context():
        updated_submission = Submission.query.filter_by(acceptance_token='test_token_789').first()
        assert updated_submission.acceptance_state == AcceptanceState.ACCEPTED
        assert updated_submission.acceptance_method == 'link'  # Should remain unchanged


def test_webhook_email_route_malformed_json(client, app):
    """Test webhook email processing with malformed JSON."""
    malformed_payload = '{"invalid": json}'
    signature = "some_signature"
    
    with patch('os.getenv', return_value="secret"):
        with patch('sister_website.app.get_forwardemail_ips_cached', return_value=['127.0.0.1']):
            response = client.post(
                '/webhook/email',
                data=malformed_payload,
                content_type='application/json',
                headers={'X-Webhook-Signature': signature},
                environ_base={'REMOTE_ADDR': '127.0.0.1'}
            )
    
    assert response.status_code == 400


def test_webhook_email_route_missing_signature_header(client, app):
    """Test webhook email processing without signature header."""
    payload = create_test_webhook_payload()
    payload_str = json.dumps(payload, separators=(',', ':'))
    
    with patch('sister_website.app.get_forwardemail_ips_cached', return_value=['127.0.0.1']):
        response = client.post(
            '/webhook/email',
            data=payload_str,
            content_type='application/json',
            # No signature header
            environ_base={'REMOTE_ADDR': '127.0.0.1'}
        )
    
    assert response.status_code == 403


@patch('sister_website.app.send_reply_confirmation_email')
def test_webhook_email_route_sends_confirmation(mock_send_email, client, app):
    """Test that webhook processing sends reply confirmation email."""
    mock_send_email.return_value = True
    
    # Create a test submission
    with app.app_context():
        submission = Submission(
            email='user@example.com',
            acceptance_token='test_token_confirm',
            acceptance_state=AcceptanceState.PENDING
        )
        db.session.add(submission)
        db.session.commit()
    
    # Create webhook payload
    payload = create_test_webhook_payload()
    payload['text'] = f"ACCEPT {submission.acceptance_token}\n\nI agree."
    payload_str = json.dumps(payload, separators=(',', ':'))
    
    secret = "test_webhook_secret"
    signature = create_webhook_signature(payload_str, secret)
    
    with patch('os.getenv', return_value=secret):
        with patch('sister_website.app.get_forwardemail_ips_cached', return_value=['127.0.0.1']):
            response = client.post(
                '/webhook/email',
                data=payload_str,
                content_type='application/json',
                headers={'X-Webhook-Signature': signature},
                environ_base={'REMOTE_ADDR': '127.0.0.1'}
            )
    
    assert response.status_code == 200
    
    # Verify confirmation email was sent
    mock_send_email.assert_called_once()
    call_args = mock_send_email.call_args[0]
    assert call_args[0] == 'user@example.com'  # recipient email
    assert call_args[2] == AcceptanceState.ACCEPTED  # acceptance state 