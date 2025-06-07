import os
import sys
import hmac
import hashlib
import json
from datetime import datetime
from flask import Flask, render_template, request, flash, redirect, url_for, session, jsonify, current_app
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
import hashlib
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect
import logging # Keep this one for current_app.logger
from pathlib import Path
# import magic # Removed, will use the one below with other Flask imports

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
    # Individual consent flags removed as per single license agreement
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
    md5sum = db.Column(db.String(32), nullable=False, index=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

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

def verify_webhook_signature(request_data, signature_header, secret_key):
    """
    Verify the webhook signature from ForwardEmail.
    
    Args:
        request_data: The raw request data (bytes or string)
        signature_header: The value of the X-Webhook-Signature header
        secret_key: The webhook secret key from ForwardEmail settings
        
    Returns:
        bool: True if signature is valid, False otherwise
    """
    if not all([request_data, signature_header, secret_key]):
        return False
        
    if isinstance(request_data, str):
        request_data = request_data.encode('utf-8')
    
    # Create HMAC signature
    expected_signature = hmac.new(
        key=secret_key.encode('utf-8'),
        msg=request_data,
        digestmod=hashlib.sha256
    ).hexdigest()
    
    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(expected_signature, signature_header)

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
    """Checks if the file's MIME type is allowed."""
    mime_type = None
    is_allowed = False
    try:
        sample = file_storage.read(2048) # Read a chunk for MIME detection
        mime_type = magic.from_buffer(sample, mime=True)
        current_app.logger.info(f"Detected MIME type: {mime_type} for file: {file_storage.filename}")
        is_allowed = mime_type in ALLOWED_MIME_TYPES
        current_app.logger.info(f"MIME type {mime_type} is_allowed: {is_allowed}")
    except ImportError as ie:
        current_app.logger.error(f"ImportError in allowed_mime (python-magic likely not installed/found): {ie}", exc_info=True)
        # Fallback: If python-magic is not available, you might choose to skip MIME check or deny all.
        # For security, denying is safer if MIME check is critical.
        is_allowed = False # Or True if you want to allow uploads if magic fails
    except Exception as e:
        current_app.logger.error(f"Exception in allowed_mime during MIME type check for {file_storage.filename}: {e}", exc_info=True)
        is_allowed = False # Default to not allowed if there's an error in checking
    finally:
        file_storage.seek(0) # IMPORTANT: Reset stream for subsequent reads
    return is_allowed

def save_screenshot(file, build_id, build_type):
    """Saves a screenshot file, calculates its MD5, and creates a Screenshot record."""
    filename_for_log = file.filename if file else "No file provided"
    current_app.logger.info(f"save_screenshot called for: {filename_for_log}")
    
    if not file:
        current_app.logger.warning(f"save_screenshot: No file object provided.")
        return None

    is_file_allowed = allowed_file(file.filename)
    current_app.logger.info(f"save_screenshot: allowed_file({file.filename}) result: {is_file_allowed}")

    if not is_file_allowed:
        current_app.logger.warning(f"save_screenshot: File extension not allowed for {file.filename}.")
        return None

    # Now check MIME type only if file extension is okay
    is_mime_allowed = allowed_mime(file)
    current_app.logger.info(f"save_screenshot: allowed_mime({file.filename}) result: {is_mime_allowed}")

    if not is_mime_allowed:
        current_app.logger.warning(f"save_screenshot: MIME type not allowed for {file.filename}.")
        return None

    # Proceed with saving if both checks passed
    if is_file_allowed and is_mime_allowed:
        filename = secure_filename(file.filename)
        upload_path_obj = Path(current_app.config['UPLOAD_FOLDER'])
        upload_path_obj.mkdir(parents=True, exist_ok=True)
        
        file_path = upload_path_obj / filename
        counter = 1
        original_filename = filename
        while file_path.exists():
            name, ext = os.path.splitext(original_filename)
            filename = f"{name}_{counter}{ext}"
            file_path = upload_path_obj / filename
            counter += 1
            
        try:
            file_content = file.read() # Read the content
            file.seek(0) # Reset stream position if file.save() needs to read it again
            file.save(file_path)
            
            md5_hash = hashlib.md5(file_content).hexdigest()
            
            new_screenshot = Screenshot(
                build_id=build_id,
                filename=filename,
                type=build_type,
                md5sum=md5_hash
            )
            return new_screenshot
        except Exception as e:
            current_app.logger.error(f"Error saving screenshot {filename}: {e}")
            return None
    # This part is reached if the initial checks (is_file_allowed and is_mime_allowed) failed earlier
    current_app.logger.warning(f"save_screenshot: Returning None for {filename_for_log} due to failed pre-checks (extension or MIME).")
    return None

def generate_acceptance_token(submission_id, email):
    """Generate a secure token for email acceptance for a Submission"""
    secret = os.getenv('SECRET_KEY', 'dev-key-please-change')
    message = f"{submission_id}:{email}".encode('utf-8')
    return hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()

def send_consent_email(email, builds, consents, submission_acceptance_token, submission_id):
    try:
        client = ForwardEmailClient(api_key=os.getenv('FORWARD_EMAIL_API_KEY'))
        
        acceptance_url = url_for('accept_license', token=submission_acceptance_token, _external=True)
        
        from_email = EmailAddress(
            email=os.getenv('FORWARD_EMAIL_FROM_EMAIL'),
            name="SISTER Team"
        )
        
        domain = os.getenv('FORWARD_EMAIL_DOMAIN', 'adhd.geek.nz')
        reply_to_local_part = f"training-data-submission-{submission_id}"
        reply_to_address = f"{reply_to_local_part}@{domain}"
        
        html_content = render_template(
            'email_template.html',
            builds=builds, 
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
                'X-SISTER-Submission-ID': str(submission_id), 
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

    current_app.logger.info(f"training_submit: form.validate_on_submit() called.")
    validation_result = form.validate_on_submit()
    current_app.logger.info(f"training_submit: form.validate_on_submit() result: {validation_result}")
    if not validation_result:
        current_app.logger.warning(f"training_submit: Form validation failed. Errors: {form.errors}")

    if validation_result:
        submission_id = str(uuid.uuid4()) 
        submission_email = form.email.data
        submission_acceptance_token = generate_acceptance_token(submission_id, submission_email)

        new_submission = Submission(
            id=submission_id,
            email=submission_email,
            acceptance_token=submission_acceptance_token
        )

        build_index = 0
        build_objects_for_submission = []
        has_screenshots = False

        build_index = 0 # Start with the first build section
        # build_objects_for_submission is already initialized
        # has_screenshots is already initialized

        while True:
            screenshots_key = f'screenshots_{build_index}'
            build_type_key = f'build_type_{build_index}'

            # Check if the form even contains these keys. If not, we're past the submitted builds.
            # A more robust check: if neither key is present in their respective dictionaries.
            if screenshots_key not in request.files and build_type_key not in request.form:
                current_app.logger.info(f"No form data (files or build_type) found for build_index {build_index}. Assuming end of builds.")
                break

            screenshots_files_list = request.files.getlist(screenshots_key)
            build_type_value = request.form.get(build_type_key) # This will be 'space' or 'ground'

            # If no build type is selected for this index, it's an incomplete section or end of data.
            if not build_type_value:
                current_app.logger.info(f"No build_type specified for build_index {build_index}. Moving to next or finishing.")
                # If there were also no files for this key, it's definitely the end or an empty section.
                if not screenshots_files_list or all(not s.filename for s in screenshots_files_list):
                    current_app.logger.info(f"Also no files for build_index {build_index}. Definitely end of relevant build sections.")
                    break # Break if no build_type and no files for this index
                build_index += 1
                continue
            
            # Filter out FileStorage objects that don't have a filename (i.e., no file was actually selected)
            actual_screenshots_files = [s for s in screenshots_files_list if s and s.filename]

            if not actual_screenshots_files:
                current_app.logger.info(f"Build section {build_index} (type: {build_type_value}) had form keys but no actual files uploaded. Skipping.")
                build_index += 1
                continue
            
            current_app.logger.info(f"Processing build_index {build_index}, type: {build_type_value}, {len(actual_screenshots_files)} file(s) submitted.")

            # Use a consistent build_id format, incorporating the original submission_id and the current build_index
            build_id = f"{new_submission.id}_build_{build_index}"
            
            current_build = Build(
                id=build_id,
                submission_id=new_submission.id
                # Potentially add: build_type=build_type_value, if your Build model stores this
            )
            
            saved_screenshots_for_this_build = []
            for file_in_request in actual_screenshots_files:
                # The 'build_type_value' ('space' or 'ground') is the correct 'build_type' for save_screenshot
                screenshot = save_screenshot(file_in_request, build_id, build_type_value) 
                if screenshot:
                    saved_screenshots_for_this_build.append(screenshot)
                    has_screenshots = True # Set to True if at least one screenshot is saved across all builds
            
            if saved_screenshots_for_this_build:
                current_build.screenshots = saved_screenshots_for_this_build
                build_objects_for_submission.append(current_build)
            else:
                current_app.logger.warning(f"Build {build_id} (type: {build_type_value}) had {len(actual_screenshots_files)} file(s) submitted, but none were saved by save_screenshot. MIME type or other issue likely.")

            build_index += 1
        
        current_app.logger.info(f"training_submit: has_screenshots = {has_screenshots}")
        if not has_screenshots:
            flash('Please upload at least one screenshot for any build type.')
            current_app.logger.warning("training_submit: No valid screenshots processed. Redirecting back to form.")
            return redirect(request.url)
        
        try:
            db.session.add(new_submission)
            for build_item in build_objects_for_submission:
                db.session.add(build_item)
            db.session.commit()
            
            # Prepare consents for email (simplified due to single license)
            # The email template should reflect the single CC BY-NC-SA 4.0 license.
            # The 'consents_for_email' dict might not even be needed if the email template is static regarding license info.
            # For now, we'll keep a simplified version for agreed_to_license if send_consent_email expects it.
            consents_for_email = {
                'agreed_to_license': form.agree_to_license.data 
            }
            
            # Send consent email
            if send_consent_email(new_submission.email, new_submission.builds, consents_for_email, new_submission.acceptance_token, new_submission.id):
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
    
    # Get the webhook secret key from environment
    webhook_secret = os.getenv('FORWARD_EMAIL_WEBHOOK_SECRET')
    if not webhook_secret:
        logger.error("Email webhook: FORWARD_EMAIL_WEBHOOK_SECRET not configured")
        return jsonify({"status": "error", "message": "Server configuration error"}), 500
    
    # Verify the request is from ForwardEmail using reverse DNS
    try:
        client_ip = request.remote_addr
        import socket
        hostname, _, _ = socket.gethostbyaddr(client_ip)
        
        allowed_domains = ['mx1.forwardemail.net', 'mx2.forwardemail.net']
        if not any(hostname.endswith(domain) for domain in allowed_domains):
            logger.warning(f"Email webhook: Rejected request from unauthorized hostname '{hostname}' (IP: {client_ip})")
            return jsonify({"status": "error", "message": "Unauthorized"}), 403
    except (socket.herror, socket.gaierror) as e:
        logger.warning(f"Email webhook: Reverse DNS lookup failed for {client_ip}: {e}")
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    except Exception as e:
        logger.error(f"Email webhook: Error during reverse DNS verification: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500
    
    # Verify webhook signature
    signature_header = request.headers.get('X-Webhook-Signature')
    if not signature_header:
        logger.warning("Email webhook: Missing X-Webhook-Signature header")
        return jsonify({"status": "error", "message": "Missing signature"}), 400
    
    # Get raw request data for signature verification
    request_data = request.get_data()
    if not verify_webhook_signature(request_data, signature_header, webhook_secret):
        logger.warning("Email webhook: Invalid webhook signature")
        return jsonify({"status": "error", "message": "Invalid signature"}), 401

    try:
        # Parse JSON data (already verified the signature)
        data = request.get_json()
        if not data:
            logger.warning("Email webhook: No JSON data received.")
            return jsonify({"status": "error", "message": "No JSON data received"}), 400
        
        #logger.info(f"Email webhook: Received data: {json.dumps(data, indent=2)}")

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
        
        logger.info(f"Email webhook: Acceptance check for submission_id='{submission_id}': in_reply='{is_acceptance_in_reply}'")
        
        if is_acceptance_in_reply:
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
            logger.info(f"Email webhook: No acceptance keywords found in email body for submission_id='{submission_id}'. No action taken.")
            return jsonify({"status": "info", "message": "No acceptance action taken based on email body."})

    except Exception as e:
        logger.error(f"Email webhook: General error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "An internal error occurred."}), 500

if __name__ == '__main__':
    # Ensure the instance directory exists
    os.makedirs(app.instance_path, exist_ok=True)
    # The upload folder and database are already initialized
    app.run(debug=True, host='0.0.0.0', port=5000)
