import os
import sys
from datetime import datetime
from flask import Flask, render_template, request, flash, redirect, url_for, session, jsonify
from flask_migrate import Migrate
import uuid # Ensure uuid is imported for new models
import magic
import re
from werkzeug.utils import secure_filename
from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField
from wtforms.validators import DataRequired, Email
from forwardemail import ForwardEmailClient, EmailMessage, EmailAddress
import hashlib
import hmac
import json
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect
import uuid
import logging

# Set up basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize extensions
db = SQLAlchemy()

# Define models before creating the app to avoid circular imports
class Submission(db.Model):
    __tablename__ = 'submission'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(120), nullable=False)
    acceptance_token = db.Column(db.String(64), unique=True, nullable=False)
    is_accepted = db.Column(db.Boolean, default=False)
    accepted_at = db.Column(db.DateTime, nullable=True)
    acceptance_method = db.Column(db.String(10), nullable=True)  # 'link' or 'email'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Relationship to Builds
    builds = db.relationship('Build', backref='submission', lazy=True)
    # Relationship to EmailLogs
    email_logs = db.relationship('EmailLog', backref='submission', lazy=True, order_by='EmailLog.received_at')
    # Relationship to LinkLogs
    link_logs = db.relationship('LinkLog', backref='submission', lazy=True, order_by='LinkLog.clicked_at')

class Build(db.Model):
    __tablename__ = 'build'
    id = db.Column(db.String(36), primary_key=True)
    submission_id = db.Column(db.String(36), db.ForeignKey('submission.id'), nullable=False)
    consent_ml_recognition = db.Column(db.Boolean, default=False)
    consent_ml_future = db.Column(db.Boolean, default=False)
    consent_test_suite = db.Column(db.Boolean, default=False)
    is_accepted = db.Column(db.Boolean, default=False) # Will be set when Submission is accepted
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    accepted_at = db.Column(db.DateTime, nullable=True) # Will be set when Submission is accepted
    acceptance_method = db.Column(db.String(10), nullable=True)  # 'link' or 'email', set when Submission is accepted
    screenshots = db.relationship('Screenshot', backref='build', lazy=True)

class Screenshot(db.Model):
    __tablename__ = 'screenshot'
    id = db.Column(db.Integer, primary_key=True)
    build_id = db.Column(db.String(36), db.ForeignKey('build.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # 'space' or 'ground'
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_test_suite = db.Column(db.Boolean, default=False)

class EmailLog(db.Model):
    __tablename__ = 'email_log'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    submission_id = db.Column(db.String(36), db.ForeignKey('submission.id'), nullable=False)
    message_id_header = db.Column(db.String(512), nullable=True, index=True)  # Message-ID header can be long and is good to index
    from_address = db.Column(db.String(255), nullable=True)
    to_address = db.Column(db.String(255), nullable=True) # The address the email was sent to (e.g., reply-to address)
    subject = db.Column(db.String(512), nullable=True)
    body_text = db.Column(db.Text, nullable=True)
    body_html = db.Column(db.Text, nullable=True)
    headers_json = db.Column(db.Text, nullable=True)  # Store all headers as a JSON string
    received_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<EmailLog {self.id} for Submission {self.submission_id}>'

class LinkLog(db.Model):
    __tablename__ = 'link_log'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    submission_id = db.Column(db.String(36), db.ForeignKey('submission.id'), nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)  # IPv4 and IPv6
    user_agent = db.Column(db.Text, nullable=True)
    clicked_at = db.Column(db.DateTime, default=datetime.utcnow)
    token_used = db.Column(db.String(64), nullable=False)

    def __repr__(self):
        return f'<LinkLog {self.id} for Submission {self.submission_id} from {self.ip_address}>'

# Create the Flask application
def create_app():
    # Load environment variables first
    env_path = os.getenv('DOTENV_PATH', '/var/www/.sister.env')
    logger.info(f"Loading environment from: {env_path}")
    load_dotenv(dotenv_path=env_path, override=True)

    # Print all relevant environment variables for debugging
    logger.info("Environment variables:")
    for var in ['UPLOAD_FOLDER', 'DATABASE_URL', 'DOTENV_PATH']:
        logger.info(f"{var} = {os.getenv(var)}")

    # Initialize Flask app
    app = Flask(__name__, instance_relative_config=True)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key-please-change')

    # Configure upload folder from environment or use default
    upload_folder = os.getenv('UPLOAD_FOLDER', os.path.join(app.instance_path, 'uploads'))
    app.config['UPLOAD_FOLDER'] = upload_folder
    app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB max file size

    # Configure database
    db_uri = os.getenv('DATABASE_URL')
    if not db_uri:
        db_uri = f'sqlite:///{os.path.join(app.instance_path, "submissions.db")}'

    # Ensure the database directory exists
    if db_uri.startswith('sqlite:'):
        db_path = db_uri.split('sqlite:///')[-1]
        if db_path != ':memory:':  # Skip directory creation for in-memory DB
            db_dir = os.path.dirname(db_path)
            if db_dir:  # Only create directory if path is not in current directory
                os.makedirs(db_dir, exist_ok=True)

    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Initialize extensions
    db.init_app(app)
    migrate = Migrate(app, db) # Initialize Flask-Migrate

    # Ensure upload directory exists
    os.makedirs(upload_folder, exist_ok=True)
    logger.info(f"Using upload folder: {upload_folder}")
    logger.info(f"Using database: {db_uri}")

    # Database creation/migration is now handled by Flask-Migrate
    # The db.create_all() call has been removed.

    return app

# Create the application
app = create_app()

# Global variables
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
ALLOWED_MIME_TYPES = {'image/png', 'image/jpeg'}

class UploadForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    agree_to_license = BooleanField(
        'I agree to license my submitted screenshots under the Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) license. ' \
        'This allows SISTER to use them for: (1) training machine learning recognition models, (2) future machine learning research, and (3) inclusion in the project\'s test suite. ' \
        'I acknowledge that this license is irrevocable for any data already distributed under these terms.',
        validators=[DataRequired(message="You must agree to the license terms to submit screenshots.")]
    )

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_mime(file_storage):
    try:
        sample = file_storage.read(2048)
        mime_type = magic.from_buffer(sample, mime=True)
    finally:
        file_storage.seek(0)
    return mime_type in ALLOWED_MIME_TYPES

def save_screenshot(file, build_id, build_type, is_test_suite=False):
    if file and allowed_file(file.filename) and allowed_mime(file):
        filename = secure_filename(file.filename)
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{build_id}_{timestamp}_{filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
        
        screenshot = Screenshot(
            build_id=build_id,
            filename=unique_filename,
            type=build_type,
            is_test_suite=is_test_suite
        )
        return screenshot
    return None

def determine_screenshot_usage(build):
    """
    Determine if screenshots should be used for test suite.
    Only returns True if test suite is the only consent given.
    """
    return (build.consent_test_suite and 
            not build.consent_ml_recognition and 
            not build.consent_ml_future)

def generate_acceptance_token(submission_id, email):
    """Generate a secure token for email acceptance for a Submission"""
    secret = os.getenv('SECRET_KEY', 'dev-key-please-change')
    message = f"{submission_id}:{email}".encode('utf-8')
    return hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()

def send_consent_email(email, builds, consents, submission_acceptance_token, submission_id):
    try:
        client = ForwardEmailClient(api_key=os.getenv('FORWARD_EMAIL_API_KEY'))
        
        # Acceptance token is now for the submission and passed as a parameter.
        # No need to generate tokens for individual builds here.
        
        acceptance_url = url_for('accept_license', token=submission_acceptance_token, _external=True)
        
        from_email = EmailAddress(
            email=os.getenv('FORWARD_EMAIL_FROM_EMAIL'),
            name="SISTER Team"
        )
        
        domain = os.getenv('FORWARD_EMAIL_DOMAIN', 'adhd.geek.nz')
        # Use the passed submission_id for reply-to and headers
        reply_to_local_part = f"training-data-submission-{submission_id}"
        reply_to_address = f"{reply_to_local_part}@{domain}"
        
        html_content = render_template(
            'email_template.html',
            builds=builds, # These are the builds associated with the submission
            consents=consents,
            acceptance_url=acceptance_url,
            timestamp=datetime.utcnow(),
            reply_to=reply_to_address 
        )
        
        message = EmailMessage(
            from_email=from_email,
            to=[email],
            subject="SISTER - Build Screenshot Submission Confirmation",
            html=html_content,
            reply_to=[reply_to_address], 
            headers={
                'X-SISTER-Submission-ID': str(submission_id), # Use submission_id and new header key
                'Reply-To': reply_to_address 
            }
        )
        
        response = client.send_email(message)
        logger.info(f"Sent consent email with reply-to: {reply_to_address} for submission ID: {submission_id}")
        return True
    except Exception as e:
        logger.error(f"Email sending error for submission ID {submission_id}: {e}", exc_info=True)
        return False

@app.route('/')
def home():
    return render_template('pages/home.html', active_page='home')

@app.route('/download')
def download():
    return render_template('pages/download.html', active_page='download')

@app.route('/documentation')
def documentation():
    return render_template('pages/documentation.html', active_page='documentation')

@app.route('/training')
def training():
    form = UploadForm()
    return render_template('pages/training.html', form=form, active_page='training')

@app.route('/training/submit', methods=['GET', 'POST'])
def training_submit():
    form = UploadForm()
    if request.method == 'GET':
        return redirect(url_for('training'))

    if form.validate_on_submit():
        # Create a single Submission record for this batch
        submission_id = str(uuid.uuid4()) # Generate ID for the submission
        submission_email = form.email.data
        # Generate acceptance token for the Submission
        submission_acceptance_token = generate_acceptance_token(submission_id, submission_email)

        new_submission = Submission(
            id=submission_id,
            email=submission_email,
            acceptance_token=submission_acceptance_token
        )

        build_objects_for_submission = []
        build_index = 0
        has_screenshots = False
        
        all_consents_given = form.agree_to_license.data # Get this once

        while True:
            screenshots = request.files.getlist(f'screenshots_{build_index}')
            build_type = request.form.get(f'build_type_{build_index}')
            
            if not any(f.filename for f in screenshots) or not build_type:
                break
                
            build_id = str(uuid.uuid4()) # Each Build still gets its own unique ID

            build = Build(
                id=build_id,
                submission_id=new_submission.id, # Link to the parent Submission
                consent_ml_recognition=all_consents_given,
                consent_ml_future=all_consents_given,
                consent_test_suite=all_consents_given
            )    
            
            saved_screenshots = []
            is_test_suite_only = determine_screenshot_usage(build) 
            
            for file in screenshots:
                if file.filename:
                    screenshot = save_screenshot(file, build_id, build_type, is_test_suite_only)
                    if screenshot:
                        saved_screenshots.append(screenshot)
                        has_screenshots = True
            
            if saved_screenshots:
                build.screenshots = saved_screenshots
                build_objects_for_submission.append(build)
            
            build_index += 1
        
        if not has_screenshots:
            flash('Please upload at least one screenshot')
            return redirect(request.url)
        
        try:
            db.session.add(new_submission)
            for build_item in build_objects_for_submission:
                db.session.add(build_item)
            db.session.commit()
            
            consents_for_email = {
                'ml_recognition': all_consents_given,
                'ml_future': all_consents_given,
                'test_suite': all_consents_given,
                'agreed_to_license': all_consents_given
            }
            
            # Pass new_submission.builds (which are the build_objects_for_submission after commit)
            # and the submission_acceptance_token to send_consent_email.
            # The signature of send_consent_email will need to be updated.
            if send_consent_email(new_submission.email, new_submission.builds, consents_for_email, new_submission.acceptance_token, new_submission.id): # Added new_submission.id
                flash('Thank you for your submission! Please check your email for the consent form.')
            else:
                flash('There was an error sending the consent email. Please try again later.')
            
        except Exception as e:
            db.session.rollback()
            flash('There was an error processing your submission. Please try again later.')
            logger.error(f"Database error in training_submit: {e}", exc_info=True)
        
        return redirect(url_for('submission_received'))

    return render_template('pages/training.html', form=form, active_page='training')

@app.route('/submission-received')
def submission_received():
    return render_template('submission_received.html', active_page='submission_received')

@app.route('/contact')
def contact():
    return render_template('pages/contact.html', active_page='contact')

@app.route('/api/accept-license/<token>', methods=['GET', 'POST'])
def accept_license(token):
    """Handle license acceptance via email link for a Submission."""
    submission = None
    if request.method == 'POST':
        # This part might be less relevant now if direct link click is the primary method
        data = request.get_json()
        token_from_post = data.get('token')
        if token_from_post:
             token = token_from_post # Allow token override from POST body

    # Find the submission by acceptance token
    submission = Submission.query.filter_by(acceptance_token=token).first()

    if not submission:
        message = "Invalid or expired acceptance link."
        if request.method == 'GET':
            flash(message, 'danger')
            return redirect(url_for('home')) # Or a more specific error page
        else: # For POST requests or other API uses
            return jsonify({"status": "error", "message": message}), 400

    if submission.is_accepted:
        message = "This submission has already been accepted."
        if request.method == 'GET':
            flash(message, 'info')
            # Pass submission to thank you page to potentially show details
            return render_template('acceptance_thank_you.html', submission=submission)
        else:
            return jsonify({"status": "info", "message": message, "accepted_at": submission.accepted_at.isoformat() if submission.accepted_at else None }), 200

    # Mark the Submission as accepted
    submission.is_accepted = True
    submission.accepted_at = datetime.utcnow()
    submission.acceptance_method = 'link'

    # Log the link click event
    try:
        new_link_log = LinkLog(
            submission_id=submission.id,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
            token_used=token,
            clicked_at=submission.accepted_at # Use the same timestamp as acceptance
        )
        db.session.add(new_link_log)
        logger.info(f"Logged link acceptance for submission {submission.id} from IP {request.remote_addr}")
    except Exception as e_link_log:
        # Log error but don't fail the acceptance if link logging fails
        logger.error(f"Failed to create LinkLog for submission {submission.id}: {e_link_log}", exc_info=True)

    # Mark all associated Builds as accepted
    for build_item in submission.builds:
        build_item.is_accepted = True
        build_item.accepted_at = submission.accepted_at # Use submission's acceptance time
        build_item.acceptance_method = 'link'
    
    try:
        db.session.commit()
        success_message = "Thank you for accepting the license for your submission!"
        if request.method == 'GET':
            flash(success_message, 'success')
            return render_template('acceptance_thank_you.html', submission=submission)
        else: # For POST requests or other API uses
            return jsonify({"status": "success", "message": success_message})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in accept_license for submission {submission.id if submission else 'unknown'}: {e}", exc_info=True)
        error_message = 'An error occurred while processing your acceptance. Please try again or contact support.'
        if request.method == 'GET':
            flash(error_message, 'danger')
            return redirect(url_for('training')) # Or a generic error page
        else:
            return jsonify({"status": "error", "message": f"Database error: {str(e)}"}), 500

def extract_reply_text(email_body_text):
    """Attempts to extract the new reply text from an email, stripping quoted original messages."""
    guard_string = "Screenshot Interrogation System for Traits and Equipment Recognition"
    processing_text = email_body_text

    guard_index = email_body_text.find(guard_string)
    if guard_index != -1:
        # If guard string is found, consider text before it as the potential reply area
        processing_text = email_body_text[:guard_index]

    lines = processing_text.splitlines()
    reply_lines = []
    
    # Common reply headers/patterns indicating start of quoted message within the potential reply area
    quote_indicators = [
        ">",  # Standard quote character
        "On ", # e.g., "On Mon, Jan 1, 2024 at 10:00 AM, User <user@example.com> wrote:"
        "From:",
        "To:",
        "Subject:",
        "Date:",
        "Sent from my iPhone", # Common mobile signature
        "Sent from my Android phone", # Common mobile signature
        "--- Original Message ---",
        "-----Original Message-----",
    ]
    # Regex to catch lines like 'On Jan 1, 2024, at 10:00 AM, User Name <user@example.com> wrote:'
    # Ensure 're' is imported at the top of your app.py
    on_date_wrote_regex = re.compile(r"^On\s+(.*?)(wrote:|écrit\s*:)", re.IGNORECASE)

    for line in lines:
        stripped_line = line.strip()
        # Check if the line indicates the start of a quoted message within the reply block
        if any(stripped_line.startswith(indicator) for indicator in quote_indicators) or \
           on_date_wrote_regex.match(stripped_line):
            # If we are processing line by line from the top and hit a quote, 
            # it means everything before this was part of the reply.
            break 
        reply_lines.append(line)
    
    return "\n".join(reply_lines).strip()

@app.route('/acceptance-thank-you')
def acceptance_thank_you():
    return render_template('acceptance_thank_you.html', active_page='acceptance_thank_you')

# Webhook endpoint for handling email replies
@app.route('/api/email-webhook', methods=['GET', 'POST'])
def handle_email_reply():
    """Handle email replies from ForwardEmail for Submissions."""
    if request.method == 'GET':
        # ForwardEmail webhook verification often uses GET for initial setup
        return jsonify({"status": "ok, webhook alive"})

    try:
        data = request.get_json()
        if not data:
            logger.warning("Email webhook: No JSON data received.")
            return jsonify({"status": "error", "message": "No JSON data received"}), 400
        
        logger.info(f"Email webhook: Received data: {json.dumps(data, indent=2)}")

        # --- START: Enhanced Header and Email Info Extraction ---
        all_headers_raw = data.get('headers', []) 
        headers_json_str = json.dumps(all_headers_raw) if all_headers_raw else None
        
        headers_dict = {}
        if isinstance(all_headers_raw, list):
            headers_dict = {h.get('key', '').lower(): h.get('value', '') for h in all_headers_raw if isinstance(h, dict) and h.get('key')}
        elif isinstance(all_headers_raw, dict): 
            headers_dict = {k.lower(): v for k, v in all_headers_raw.items()}

        message_id_value = headers_dict.get('message-id')

        from_email_data = data.get('from', []) 
        from_email_address = None
        if isinstance(from_email_data, list) and from_email_data:
            sender_obj = from_email_data[0]
            if isinstance(sender_obj, dict):
                from_email_address = sender_obj.get('address', '').lower() or sender_obj.get('email', '').lower()
        elif isinstance(from_email_data, dict): 
            from_email_address = from_email_data.get('address', '').lower() or from_email_data.get('email', '').lower()

        to_email_address = None
        envelope_recipients = data.get('envelopeRecipients', []) 
        if isinstance(envelope_recipients, list) and envelope_recipients:
            if isinstance(envelope_recipients[0], str):
                to_email_address = envelope_recipients[0].lower()
        
        if not to_email_address:
            to_data_field = data.get('to', []) 
            if isinstance(to_data_field, list) and to_data_field:
                recipient_obj = to_data_field[0]
                if isinstance(recipient_obj, dict):
                    to_email_address = recipient_obj.get('address', '').lower() or recipient_obj.get('email', '').lower()
            elif isinstance(to_data_field, dict): 
                to_email_address = to_data_field.get('address', '').lower() or to_data_field.get('email', '').lower()
        # --- END: Enhanced Header and Email Info Extraction ---
        
        submission_id = None
        
        username_param = request.args.get('username', '')
        logger.info(f"Email webhook: Extracted username from query params: '{username_param}'")
        if username_param.startswith('training-data-submission-'):
            try:
                submission_id = username_param.split('training-data-submission-')[-1]
                logger.info(f"Email webhook: Extracted submission_id from username: '{submission_id}'")
            except (IndexError, ValueError) as e:
                logger.warning(f"Email webhook: Error extracting submission_id from username '{username_param}': {e}")
                submission_id = None

        if not submission_id:
            submission_id_from_header = headers_dict.get('x-sister-submission-id')
            if submission_id_from_header:
                submission_id = submission_id_from_header
                logger.info(f"Email webhook: Extracted submission_id from header 'X-SISTER-Submission-ID': '{submission_id}'")

        if not submission_id:
            logger.warning("Email webhook: Could not determine submission_id. From/To/Subject/MsgID: {from_email_address}/{to_email_address}/{data.get('subject')}/{message_id_value}")
            return jsonify({"status": "error", "message": "Could not identify submission from email reply."}), 400

        email_text_content = data.get('text', '')
        email_subject = data.get('subject', '')
        
        logger.info(f"Email webhook: Processing reply for submission_id='{submission_id}', from='{from_email_address}', to='{to_email_address}', subject='{email_subject}', msg_id='{message_id_value}'")

        reply_only_text = extract_reply_text(email_text_content)
        logger.info(f"Email webhook: Extracted reply-only text (first 200 chars): '{reply_only_text[:200]}...' (length: {len(reply_only_text)})")

        acceptance_keywords = ['accept', 'confirm', 'yes', 'agreed', 'agreement', 'consent'] # Added 'consent'
        is_acceptance_in_reply = any(keyword in reply_only_text.lower() for keyword in acceptance_keywords)
        is_acceptance_in_subject = any(keyword in email_subject.lower() for keyword in acceptance_keywords)
        
        is_acceptance = is_acceptance_in_reply or is_acceptance_in_subject
        logger.info(f"Email webhook: Acceptance check for submission_id='{submission_id}': in_reply='{is_acceptance_in_reply}', in_subject='{is_acceptance_in_subject}', overall='{is_acceptance}'")
        
        if is_acceptance:
            submission = Submission.query.get(submission_id)
            
            if not submission:
                logger.warning(f"Email webhook: Submission with ID '{submission_id}' not found.")
                return jsonify({"status": "error", "message": f"Submission {submission_id} not found."}), 404

            # Log the received email now that we have a valid submission
            try:
                email_html_content = data.get('html', '') # Get HTML content if available
                new_email_log = EmailLog(
                    submission_id=submission.id,
                    message_id_header=message_id_value,
                    from_address=from_email_address,
                    to_address=to_email_address,
                    subject=email_subject,
                    body_text=email_text_content,
                    body_html=email_html_content,
                    headers_json=headers_json_str
                )
                db.session.add(new_email_log)
                db.session.commit()
                logger.info(f"Email webhook: Email log created for submission_id='{submission.id}', message_id='{message_id_value}' to EmailLog ID {new_email_log.id}.")
            except Exception as e_log:
                db.session.rollback()
                logger.error(f"Email webhook: Failed to log email for submission_id='{submission.id}': {e_log}", exc_info=True)
                # Continue processing acceptance even if logging failed for now.

            if submission.is_accepted:
                logger.info(f"Email webhook: Submission '{submission_id}' already accepted on {submission.accepted_at} by {submission.acceptance_method}.")
                return jsonify({"status": "info", "message": f"Submission {submission_id} already accepted."}), 200 # OK, already done

            submission.is_accepted = True
            submission.accepted_at = datetime.utcnow()
            submission.acceptance_method = 'email'

            for build_item in submission.builds:
                build_item.is_accepted = True
                build_item.accepted_at = submission.accepted_at
                build_item.acceptance_method = 'email'
            
            try:
                db.session.commit()
                logger.info(f"Email webhook: Successfully accepted Submission '{submission_id}' and its builds via email reply.")
                return jsonify({"status": "success", "message": f"Submission {submission_id} accepted via email."})
            except Exception as e_commit:
                db.session.rollback()
                logger.error(f"Email webhook: Database error committing acceptance for submission_id '{submission_id}': {e_commit}", exc_info=True)
                return jsonify({"status": "error", "message": "Database error during acceptance."}), 500
        else:
            logger.info(f"Email webhook: No acceptance keywords found in reply for submission_id='{submission_id}'. No action taken.")
            return jsonify({"status": "info", "message": "No acceptance action taken."})

    except Exception as e:
        logger.error(f"Email webhook: General error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "An internal error occurred."}), 500

if __name__ == '__main__':
    # Ensure the instance directory exists
    os.makedirs(app.instance_path, exist_ok=True)
    # The upload folder and database are already initialized
    app.run(debug=True, host='0.0.0.0', port=5000)
