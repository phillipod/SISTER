import os
import hmac
import hashlib
from datetime import datetime
import logging

from flask import render_template, url_for
from forwardemail import ForwardEmailClient, EmailMessage, EmailAddress

logger = logging.getLogger(__name__)


def send_consent_email(email, builds, consents, submission_acceptance_token, submission_id):
    try:
        client = ForwardEmailClient(api_key=os.getenv('FORWARD_EMAIL_API_KEY'))

        acceptance_url = url_for('accept_license', token=submission_acceptance_token, _external=True)
        decline_url = url_for('decline_license', token=submission_acceptance_token, _external=True)

        domain = os.getenv('FORWARD_EMAIL_DOMAIN', 'adhd.geek.nz')
        reply_to_local_part = f"training-data-submission-{submission_id}"
        reply_to_address = f"{reply_to_local_part}@{domain}"

        # Use the same address for both From and Reply-To
        from_email = EmailAddress(
            email=reply_to_address,
            name="SISTER Team"
        )

        html_content = render_template(
            'email_template.html',
            builds=builds,
            consents=consents,
            acceptance_url=acceptance_url,
            decline_url=decline_url,
            timestamp=datetime.utcnow(),
            reply_to=reply_to_address
        )

        message = EmailMessage(
            from_email=from_email,
            to=[email],
            subject=f"SISTER - Build Screenshot Confirmation - Submission {submission_id}",
            html=html_content,
            reply_to=reply_to_address,
            headers={
                'X-SISTER-Submission-ID': str(submission_id)
            }
        )

        client.send_email(message)
        logger.info(f"Sent consent email with reply-to: {reply_to_address} for submission ID: {submission_id}")
        return True
    except Exception as e:
        logger.error(f"Email sending error for submission ID {submission_id}: {e}", exc_info=True)
        return False


def send_reply_confirmation_email(original_sender_email, submission_id, decision_text, reply_channel_address, submission_token=None):
    if not original_sender_email or not submission_id or not reply_channel_address:
        log_submission_id = submission_id if submission_id else "<Not Provided>"
        logger.warning(
            f"Cannot attempt to send reply confirmation for '{decision_text.lower()}' "
            f"for submission ID '{log_submission_id}' due to missing critical details: "
            f"Sender Email ({'Present' if original_sender_email else 'MISSING'}), "
            f"Reply Channel ({'Present' if reply_channel_address else 'MISSING'})."
        )
        return False

    try:
        client = ForwardEmailClient(api_key=os.getenv('FORWARD_EMAIL_API_KEY'))

        # Use the same address for both From and Reply-To
        from_email_obj = EmailAddress(
            email=reply_channel_address,
            name="SISTER Team"
        )

        to_email_recipient = EmailAddress(email=original_sender_email)

        subject = f"SISTER - Reply Processed for Submission {submission_id}: {decision_text}"

        withdrawal_url = None
        if submission_token:
            withdrawal_url = url_for('withdraw_submission', token=submission_token, _external=True)

        html_content = render_template(
            'reply_email_template.html',
            submission_id=submission_id,
            decision_text=decision_text,
            withdrawal_url=withdrawal_url,
            timestamp=datetime.utcnow()
        )

        message = EmailMessage(
            from_email=from_email_obj,
            to=[to_email_recipient],
            subject=subject,
            html=html_content,
            reply_to=reply_channel_address,
            headers={
                'X-SISTER-Submission-ID': str(submission_id),
                'Auto-Submitted': 'auto-replied',
                'X-SISTER-Autoresponse-Type': 'reply-confirmation'
            }
        )

        client.send_email(message)
        logger.info(
            f"Successfully sent reply confirmation email to '{original_sender_email}' for submission ID '{submission_id}'. "
            f"From: '{reply_channel_address}', Decision: '{decision_text}'."
        )
        return True
    except Exception as e:
        logger.error(
            f"Error sending reply confirmation email for submission ID '{submission_id}' to '{original_sender_email}': {e}",
            exc_info=True
        )
        return False


def verify_webhook_signature(request_data, signature_header, secret_key):
    if not all([request_data, signature_header, secret_key]):
        return False

    if isinstance(request_data, str):
        request_data = request_data.encode('utf-8')

    expected_signature = hmac.new(
        key=secret_key.encode('utf-8'),
        msg=request_data,
        digestmod=hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature_header)
