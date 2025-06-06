import os
import sys
from datetime import datetime
from flask import Flask, render_template, request, flash, redirect, url_for, session, jsonify
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
class Build(db.Model):
    __tablename__ = 'build'
    id = db.Column(db.String(36), primary_key=True)
    email = db.Column(db.String(120), nullable=False)
    consent_ml_recognition = db.Column(db.Boolean, default=False)
    consent_ml_future = db.Column(db.Boolean, default=False)
    consent_test_suite = db.Column(db.Boolean, default=False)
    is_accepted = db.Column(db.Boolean, default=False)
    acceptance_token = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    accepted_at = db.Column(db.DateTime, nullable=True)
    acceptance_method = db.Column(db.String(10), nullable=True)  # 'link' or 'email'
    screenshots = db.relationship('Screenshot', backref='build', lazy=True)

class Screenshot(db.Model):
    __tablename__ = 'screenshot'
    id = db.Column(db.Integer, primary_key=True)
    build_id = db.Column(db.String(36), db.ForeignKey('build.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # 'space' or 'ground'
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_test_suite = db.Column(db.Boolean, default=False)

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

    # Ensure upload directory exists
    os.makedirs(upload_folder, exist_ok=True)
    logger.info(f"Using upload folder: {upload_folder}")
    logger.info(f"Using database: {db_uri}")

    # Create database tables
    with app.app_context():
        try:
            db.create_all()
            logger.info("Database tables created/verified")
            # Verify tables exist
            inspector = inspect(db.engine)
            logger.info(f"Existing tables: {inspector.get_table_names()}")
        except Exception as e:
            logger.error(f"Error initializing database: {e}", exc_info=True)
            raise

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

def generate_acceptance_token(build_id, email):
    """Generate a secure token for email acceptance"""
    secret = os.getenv('SECRET_KEY', 'dev-key-please-change')
    message = f"{build_id}:{email}".encode('utf-8')
    return hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()

def send_consent_email(email, builds, consents):
    try:
        # Initialize the ForwardEmail client
        client = ForwardEmailClient(api_key=os.getenv('FORWARD_EMAIL_API_KEY'))
        
        # Create acceptance tokens for each build
        for build in builds:
            build.acceptance_token = generate_acceptance_token(build.id, email)
        
        db.session.commit()
        
        # Generate the acceptance URL for the first build
        acceptance_url = url_for('accept_license', token=builds[0].acceptance_token, _external=True)
        
        # Prepare email content
        from_email = EmailAddress(
            email=os.getenv('FORWARD_EMAIL_FROM_EMAIL'),
            name="SISTER Team"
        )
        
        # Create a reply-to address that includes the build ID
        # Format: training-data-submission-{build_id}@domain
        domain = os.getenv('FORWARD_EMAIL_DOMAIN', 'adhd.geek.nz')
        build_id = str(builds[0].id)
        reply_to_local = f"training-data-submission-{build_id}@{domain}"
        
        # Render the email template with acceptance link
        html_content = render_template(
            'email_template.html',
            builds=builds,
            consents=consents,
            acceptance_url=acceptance_url,
            timestamp=datetime.utcnow(),
            reply_to=reply_to_local  # Pass to template if needed
        )
        
        # Create and send the email
        message = EmailMessage(
            from_email=from_email,
            to=[email],
            subject="SISTER - Build Screenshot Submission Confirmation",
            html=html_content,
            reply_to=[reply_to_local],  # Use the build-specific reply-to address
            headers={
                'X-SISTER-Build-ID': build_id,
                'Reply-To': reply_to_local  # Ensure it's in headers too
            }
        )
        
        # Send the email
        response = client.send_email(message)
        print(f"Sent email with reply-to: {reply_to_local}")
        return True
    except Exception as e:
        print(f"Email sending error: {e}")
        import traceback
        traceback.print_exc()
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
        builds = []
        build_index = 0
        has_screenshots = False
        
        while True:
            screenshots = request.files.getlist(f'screenshots_{build_index}')
            build_type = request.form.get(f'build_type_{build_index}')
            
            if not any(f.filename for f in screenshots) or not build_type:
                break
                
            build_id = str(uuid.uuid4())
            token = generate_acceptance_token(build_id, form.email.data)
            # If agree_to_license is checked, all underlying consents are true
            all_consents_given = form.agree_to_license.data

            build = Build(
                id=str(build_id),
                email=form.email.data,
                consent_ml_recognition=all_consents_given,
                consent_ml_future=all_consents_given,
                consent_test_suite=all_consents_given,
                acceptance_token="placeholder_token"  # Will be generated by send_consent_email
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
                builds.append(build)
            
            build_index += 1
        
        if not has_screenshots:
            flash('Please upload at least one screenshot')
            return redirect(request.url)
        
        try:
            for build in builds:
                db.session.add(build)
            db.session.commit()
            
            # The 'consents' dict for the email template might now just confirm the overall agreement
            # or we can still pass the individual flags if the template uses them for display.
            # For now, let's keep passing them based on the single checkbox.
            all_consents_given = form.agree_to_license.data
            consents = {
                'ml_recognition': all_consents_given,
                'ml_future': all_consents_given,
                'test_suite': all_consents_given,
                'agreed_to_license': all_consents_given # Add a flag for the overall license agreement
            }            
            if send_consent_email(form.email.data, builds, consents):
                flash('Thank you for your submission! Please check your email for the consent form.')
            else:
                flash('There was an error sending the consent email. Please try again later.')
            
        except Exception as e:
            db.session.rollback()
            flash('There was an error processing your submission. Please try again later.')
            print(f"Database error: {e}")
        
        return redirect(url_for('training'))

    return render_template('pages/training.html', form=form, active_page='training')

@app.route('/contact')
def contact():
    return render_template('pages/contact.html', active_page='contact')

@app.route('/api/accept-license/<token>', methods=['GET', 'POST'])
def accept_license(token):
    """Handle license acceptance via email link"""
    if request.method == 'POST':
        # Handle form submission if needed
        data = request.get_json()
        token = data.get('token')
    
    # Find the build by acceptance token
    build = Build.query.filter_by(acceptance_token=token, is_accepted=False).first()
    
    if not build:
        return jsonify({"status": "error", "message": "Invalid or expired token"}), 400
    
    # Update the build to mark as accepted
    build.is_accepted = True
    build.accepted_at = datetime.utcnow()
    build.acceptance_method = 'link'
    
    try:
        db.session.commit()
        if request.method == 'GET':
            return render_template('acceptance_thank_you.html', build=build)
        else: # For POST requests or other API uses
            return jsonify({"status": "success", "message": "Thank you for accepting the license!"})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in accept_license: {e}", exc_info=True)
        if request.method == 'GET':
            flash('An error occurred while processing your acceptance. Please try again or contact support.', 'danger')
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

# Webhook endpoint for handling email replies
@app.route('/api/email-webhook', methods=['GET', 'POST'])
def handle_email_reply():
    """Handle email replies from ForwardEmail"""
    # ForwardEmail webhook verification
    if request.method == 'GET':
        return jsonify({"status": "ok"})
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No JSON data received"}), 400
        
        # Log the incoming request for debugging
        print(f"Received webhook with data: {json.dumps(data, indent=2)}")
        
        # Get the username from query parameters (extracted by ForwardEmail)
        username = request.args.get('username', '')
        print(f"Extracted username from query params: {username}")
        
        # Extract build ID from username (format: training-data-submission-{build_id})
        build_id = None
        if username.startswith('training-data-submission-'):
            try:
                build_id = username.split('-')[-1]  # Get the last part after the last dash
                print(f"Extracted build ID from username: {build_id}")
            except (IndexError, ValueError) as e:
                print(f"Error extracting build ID from username: {e}")
        
        # Extract email information from the webhook payload
        from_email = None
        email_text = ''
        subject = ''
        
        # Handle different possible structures in the webhook payload
        if 'from' in data:
            # Handle the main 'from' field which could be an object or array
            if isinstance(data['from'], dict) and 'address' in data['from']:
                from_email = data['from']['address']
            elif isinstance(data['from'], list) and len(data['from']) > 0:
                if 'address' in data['from'][0]:
                    from_email = data['from'][0]['address']
        
        # Extract email content
        if 'text' in data:
            email_text = data['text'].lower()
        if 'subject' in data:
            subject = data['subject']
        
        # Log the received email details
        print(f"Received email from: {from_email}")
        print(f"Subject: {subject}")
        print(f"Build ID from email address: {build_id}")
        
        if not from_email:
            return jsonify({"status": "error", "message": "No valid from email found"}), 400
        
        # Extract the new reply text, attempting to strip quoted original message
        reply_only_text = extract_reply_text(data.get('text', ''))
        logger.info(f"Extracted reply-only text: '{reply_only_text[:200]}...' (length: {len(reply_only_text)})")

        # Look for acceptance keywords ONLY in the new reply text or the subject
        acceptance_keywords = ['accept', 'confirm', 'yes', 'agreed', 'agreement']
        is_acceptance_in_reply = any(keyword in reply_only_text.lower() for keyword in acceptance_keywords)
        is_acceptance_in_subject = any(keyword in subject.lower() for keyword in acceptance_keywords)
        
        is_acceptance = is_acceptance_in_reply or is_acceptance_in_subject
        logger.info(f"Acceptance check: in_reply='{is_acceptance_in_reply}', in_subject='{is_acceptance_in_subject}', overall='{is_acceptance}'")
        
        if is_acceptance:
            build = None
            
            # First try to find build by the ID from the email address
            if build_id:
                build = Build.query.get(build_id)
                print(f"Found build by ID {build_id} from email address: {build}")
            
            # Fallback: check headers (for backward compatibility)
            if not build and 'headers' in data:
                headers = {}
                if isinstance(data['headers'], list):
                    headers = {h.get('key', '').lower(): h.get('value', '') for h in data['headers']}
                elif isinstance(data['headers'], dict):
                    headers = {k.lower(): v for k, v in data['headers'].items()}
                
                build_id_from_header = headers.get('x-sister-build-id')
                if build_id_from_header:
                    build = Build.query.get(build_id_from_header)
                    print(f"Found build by header ID {build_id_from_header}: {build}")
            
            # Last resort: find most recent unaccepted build for this email
            if not build:
                build = Build.query.filter_by(
                    email=from_email,
                    is_accepted=False
                ).order_by(Build.created_at.desc()).first()
                print(f"Found most recent unaccepted build for {from_email}: {build}")
            
            if build:
                build.is_accepted = True
                build.accepted_at = datetime.utcnow()
                build.acceptance_method = 'email'
                db.session.commit()
                print(f"Accepted license for build {build.id} via email reply")
                return jsonify({"status": "success", "message": "License accepted"})
        
        print(f"No action taken for email from {from_email}")
        return jsonify({"status": "ignored", "message": "No action taken"})
    
    except Exception as e:
        error_msg = f"Error processing email reply: {str(e)}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": error_msg}), 500

if __name__ == '__main__':
    # Ensure the instance directory exists
    os.makedirs(app.instance_path, exist_ok=True)
    # The upload folder and database are already initialized
    app.run(debug=True, host='0.0.0.0', port=5000)
