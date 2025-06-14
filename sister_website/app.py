import os
import hmac
import hashlib
import json
import logging
from datetime import datetime, timedelta
from flask import (
    Flask,
    render_template,
    request,
    flash,
    redirect,
    url_for,
    session,
    jsonify,
    current_app,
    send_file,
)
from flask_migrate import Migrate
from flask_caching import Cache
from flask_wtf import CSRFProtect
from urllib.parse import urlparse, urljoin
import uuid  # Ensure uuid is imported for new models
import magic
import re
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from io import BytesIO
import requests

from .models import (
    db,
    Submission,
    Build,
    Screenshot,
    EmailLog,
    LinkLog,
    AdminUser,
    AcceptanceState,
    DatasetLabel,
)
from .forms import UploadForm, LoginForm, AdminUserForm, ChangePasswordForm, DatasetLabelForm
from .email_utils import (
    send_consent_email,
    send_reply_confirmation_email,
    verify_webhook_signature,
)
# import magic # Removed, will use the one below with other Flask imports

# Initialize extensions
cache = Cache()
csrf = CSRFProtect()

def create_app():
    # Load environment variables first
    env_path = os.getenv('DOTENV_PATH', '/var/www/.sister.env')
    load_dotenv(dotenv_path=env_path, override=True)

    # Initialize Flask app
    app = Flask(__name__, instance_relative_config=True)

    # Configure logging
    log_level = os.getenv('FLASK_LOG_LEVEL', 'INFO').upper()
    app.logger.setLevel(log_level)

    # Now that we have an app, we can use its logger.
    app.logger.info(f"Log level set to {log_level}")
    app.logger.info(f"Loading environment from: {env_path}")

    # Only print environment variables when running in debug mode to avoid leaking paths in logs
    if app.logger.isEnabledFor(logging.DEBUG):
        app.logger.debug("Environment variables (debug):")
        for var in ['UPLOAD_FOLDER', 'DATABASE_URL', 'DOTENV_PATH']:
            app.logger.debug(f"{var} = {os.getenv(var)}")

    # SECRET_KEY is mandatory in production – abort startup if missing
    secret_key = os.getenv('SECRET_KEY')
    if not secret_key:
        raise RuntimeError("SECRET_KEY environment variable must be set for secure operation.")
    app.config['SECRET_KEY'] = secret_key
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'
    # Short lifetime for admin sessions (default 30 minutes, configurable via env)
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(
        minutes=int(os.getenv('SESSION_LIFETIME_MINUTES', '30'))
    )

    # Configure upload folder from environment or use default
    upload_folder = os.getenv(
        'UPLOAD_FOLDER', os.path.join(app.instance_path, 'uploads')
    )
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

    # Configure cache
    app.config['CACHE_TYPE'] = 'simple'
    app.config['CACHE_DEFAULT_TIMEOUT'] = 900  # 15 minutes

    # Initialize extensions
    db.init_app(app)
    Migrate(app, db)  # Initialize Flask-Migrate
    cache.init_app(app)
    csrf.init_app(app)

    # Ensure upload directory exists
    os.makedirs(upload_folder, exist_ok=True)
    app.logger.info(f"Using upload folder: {upload_folder}")
    app.logger.info(f"Using database: {db_uri}")

    # Database creation/migration is now handled by Flask-Migrate
    # The db.create_all() call has been removed.

    return app


# Create the application
app = create_app()

@app.cli.command('create-admin')
def create_admin_command():
    """Creates the default admin user from environment variables."""
    with app.app_context():
        default_user = os.getenv('ADMIN_USERNAME')
        default_pass = os.getenv('ADMIN_PASSWORD')
        if not default_user or not default_pass:
            print('ADMIN_USERNAME and ADMIN_PASSWORD must be set in the environment.')
            return

        existing = AdminUser.query.filter_by(username=default_user).first()
        if existing:
            print(f"Admin user '{default_user}' already exists.")
            return

        new_user = AdminUser(username=default_user)
        new_user.set_password(default_pass)
        db.session.add(new_user)
        db.session.commit()
        print(f"Admin user '{default_user}' created successfully.")

# Global variables
ALLOWED_MIME_TYPES = {'image/png', 'image/jpeg'}

# Cache for ForwardEmail MX IP addresses
_forwardemail_ips = []
_forwardemail_ips_last_fetch = None


def _fetch_forwardemail_ips():
    """Download the list of ForwardEmail MX server IPs."""
    url = "https://forwardemail.net/ips.json"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()
    mx_hosts = {"mx1.forwardemail.net", "mx2.forwardemail.net"}
    ips = []
    for entry in data:
        if entry.get("hostname") in mx_hosts:
            ips.extend(entry.get("ipv4", []))
            ips.extend(entry.get("ipv6", []))
    return ips


def get_forwardemail_ips():
    """Return cached ForwardEmail MX IPs, refreshing every 24 hours."""
    global _forwardemail_ips, _forwardemail_ips_last_fetch
    if (
        _forwardemail_ips_last_fetch is None
        or datetime.utcnow() - _forwardemail_ips_last_fetch > timedelta(hours=24)
    ):
        try:
            _forwardemail_ips = _fetch_forwardemail_ips()
            _forwardemail_ips_last_fetch = datetime.utcnow()
            current_app.logger.info(
                "Fetched ForwardEmail IP list containing %d entries",
                len(_forwardemail_ips),
            )
        except Exception as e:
            current_app.logger.error(f"Failed to fetch ForwardEmail IP list: {e}")
    return _forwardemail_ips


def allowed_mime(file_storage):
    """Checks if the file's MIME type is allowed and returns the MIME type if so."""
    mime_type = None
    try:
        sample = file_storage.read(2048)  # Read a chunk for MIME detection
        mime_type = magic.from_buffer(sample, mime=True)
        current_app.logger.info(
            "Detected MIME type: %s for file: %s", mime_type, file_storage.filename
        )
        if mime_type in ALLOWED_MIME_TYPES:
            current_app.logger.info("MIME type %s is allowed.", mime_type)
            return mime_type
        
        current_app.logger.warning("MIME type %s is not allowed.", mime_type)
        return None

    except ImportError as ie:
        current_app.logger.error("ImportError in allowed_mime: %s", ie, exc_info=True)
        return None  # Fallback if python-magic is not available
    except Exception as e:
        current_app.logger.error(
            "Exception in allowed_mime for %s: %s", file_storage.filename, e,
            exc_info=True,
        )
        return None  # Default to not allowed if there's an error in checking
    finally:
        file_storage.seek(0)  # IMPORTANT: Reset stream for subsequent reads


def is_safe_url(target):
    """Validate a target URL to prevent open redirects."""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc

def is_admin():
    """Return True if the current session belongs to a valid, unlocked admin."""
    admin_id = session.get('admin_user_id')
    if not admin_id:
        return False
    user = AdminUser.query.get(admin_id)
    return user is not None and not user.is_locked

def save_screenshot(file, filename_base=None):
    """Saves a screenshot file, calculates its MD5, and creates a Screenshot record in memory without saving to disk."""
    filename_for_log = file.filename if file else "No file provided"
    current_app.logger.info(f"save_screenshot called for: {filename_for_log}")
    
    if not file:
        current_app.logger.warning(f"save_screenshot: No file object provided.")
        return None

    # Check MIME type from file content, which is the single source of truth
    detected_mime_type = allowed_mime(file)
    if not detected_mime_type:
        current_app.logger.warning(f"save_screenshot: MIME type not allowed or could not be determined for {filename_for_log}.")
        return None

    # Determine extension from the validated MIME type
    extension_map = {'image/png': 'png', 'image/jpeg': 'jpg'}
    extension = extension_map.get(detected_mime_type)

    if not extension:
        # This case should not be reached if ALLOWED_MIME_TYPES and extension_map are in sync
        current_app.logger.error(f"Could not determine file extension for validated MIME type: {detected_mime_type}")
        return None
    
    # Construct filename
    if filename_base:
        filename = f"{filename_base}.{extension}"
    else:
        # Fallback to a secured version of the original filename if no base is provided
        filename = secure_filename(file.filename)
            
    try:
        file_content = file.read()  # Read the content once
        file.seek(0)  # Reset stream position in case it's used elsewhere, good practice.

        md5_hash = hashlib.md5(file_content).hexdigest()

        new_screenshot = Screenshot(
            filename=filename,
            md5sum=md5_hash,
            data=file_content,
        )
        return new_screenshot
    except Exception as e:
        current_app.logger.error(f"Error processing screenshot data for {filename}: {e}")
        return None

def generate_acceptance_token(submission_id, email):
    """Generate a secure token for email acceptance for a Submission"""
    secret = current_app.config['SECRET_KEY']
    message = f"{submission_id}:{email}".encode('utf-8')
    return hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()


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
def training_redirect():
    # Permanent redirect from /training to /training-data
    return redirect(url_for('training_data'), code=301)

@app.route('/training-data')
def training_data():
    form = UploadForm()
    return render_template('pages/training_data.html', form=form, active_page='training_data')

@app.route('/training-data/submit', methods=['GET', 'POST'])
def training_data_submit():
    form = UploadForm()
    if request.method == 'GET':
        return redirect(url_for('training_data'))

    current_app.logger.info(f"training_data_submit: form.validate_on_submit() called.")
    validation_result = form.validate_on_submit()
    current_app.logger.info(f"training_data_submit: form.validate_on_submit() result: {validation_result}")
    if not validation_result:
        current_app.logger.warning(f"training_data_submit: Form validation failed. Errors: {form.errors}")

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
            build_platform_key = f'build_platform_{build_index}'

            # Check if the form even contains these keys. If not, we're past the submitted builds.
            if (screenshots_key not in request.files and 
                build_type_key not in request.form and 
                build_platform_key not in request.form):
                current_app.logger.info(f"No form data (files, build_type, or build_platform) found for build_index {build_index}. Assuming end of builds.")
                break

            screenshots_files_list = request.files.getlist(screenshots_key)
            build_type_value = request.form.get(build_type_key) # This will be 'space' or 'ground'
            build_platform_value = request.form.get(build_platform_key) # This will be 'PC' or 'Console'

            # If no build type or platform is selected for this index, it's an incomplete section or end of data.
            if not build_type_value or not build_platform_value:
                current_app.logger.info(f"No build_type ('{build_type_value}') or build_platform ('{build_platform_value}') specified for build_index {build_index}. Moving to next or finishing.")
                # If there were also no files for this key, it's definitely the end or an empty section.
                if not screenshots_files_list or all(not s.filename for s in screenshots_files_list):
                    current_app.logger.info(f"Also no files for build_index {build_index}. Definitely end of relevant build sections.")
                    break # Break if no build_type/platform and no files for this index
                build_index += 1
                continue
            
            # Filter out FileStorage objects that don't have a filename (i.e., no file was actually selected)
            actual_screenshots_files = [s for s in screenshots_files_list if s and s.filename]

            if not actual_screenshots_files:
                current_app.logger.info(f"Build section {build_index} (type: {build_type_value}) had form keys but no actual files uploaded. Skipping.")
                build_index += 1
                continue
            
            current_app.logger.info(f"Processing build_index {build_index}, platform: {build_platform_value}, type: {build_type_value}, {len(actual_screenshots_files)} file(s) submitted.")

            # Let the database handle the build_id generation via its default
            current_build = Build(
                submission_id=new_submission.id,
                platform=build_platform_value,
                type=build_type_value
            )
            
            saved_screenshots_for_this_build = []
            for i, file_in_request in enumerate(actual_screenshots_files, 1):
                new_filename_base = f"build_{build_index}_{i:02d}"
                screenshot = save_screenshot(file_in_request, filename_base=new_filename_base) 
                if screenshot:
                    saved_screenshots_for_this_build.append(screenshot)
                    has_screenshots = True # Set to True if at least one screenshot is saved across all builds
            
            if saved_screenshots_for_this_build:
                current_build.screenshots = saved_screenshots_for_this_build
                build_objects_for_submission.append(current_build)
            else:
                current_app.logger.warning(f"Build {current_build.id} (platform: {build_platform_value}, type: {build_type_value}) had {len(actual_screenshots_files)} file(s) submitted, but none were saved by save_screenshot. MIME type or other issue likely.")

            build_index += 1
        
        current_app.logger.info(f"training_data_submit: has_screenshots = {has_screenshots}")
        if not has_screenshots:
            flash('Please upload at least one screenshot for any build type.')
            current_app.logger.warning("training_data_submit: No valid screenshots processed. Redirecting back to form.")
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
            email_sent = send_consent_email(new_submission.email, new_submission.builds, consents_for_email, new_submission.acceptance_token, new_submission.id)
            db.session.commit()  # Ensure everything is committed before redirecting
            
            if email_sent:
                flash('Thank you for your submission! Please check your email for the consent form.', 'success')
            else:
                flash('Your submission was received, but there was an error sending the confirmation email. We have your data and will process it shortly.', 'warning')
            
            return redirect(url_for('submission_received'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error in training_data_submit: {e}", exc_info=True)
            flash('There was an error processing your submission. Please try again later.', 'danger')
            return redirect(url_for('training_data'))

    return redirect(url_for('training_data'))

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
            # Clear any existing messages before setting the info message
            session.pop('_flashes', None)
            flash(message, 'info')
            # Pass submission to thank you page to potentially show details
            return render_template('acceptance_thank_you.html', submission=submission)
        else:
            return jsonify({"status": "info", "message": message, "accepted_at": submission.accepted_at.isoformat() if submission.accepted_at else None }), 200

    if submission.acceptance_state != AcceptanceState.PENDING:
        message = f"This submission has already been {submission.acceptance_state.value} and cannot be changed."
        if request.method == 'GET':
            flash(message, 'warning')
            return redirect(url_for('home'))
        else:
            return jsonify({"status": "error", "message": message}), 409 # 409 Conflict

    # Mark the Submission as accepted
    submission.acceptance_state = AcceptanceState.ACCEPTED
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
        current_app.logger.info(f"Logged link acceptance for submission {submission.id} from IP {request.remote_addr}")
    except Exception as e_link_log:
        # Log error but don't fail the acceptance if link logging fails
        current_app.logger.error(f"Failed to create LinkLog for submission {submission.id}: {e_link_log}", exc_info=True)

    # The logic to update builds is no longer needed here since the build status
    # is now derived from the submission's status.
    
    try:
        db.session.commit()

        # After successfully saving, send a confirmation email with the withdrawal link.
        try:
            domain = os.getenv('FORWARD_EMAIL_DOMAIN', 'adhd.geek.nz')
            reply_to_address = f"training-data-submission-{submission.id}@{domain}"
            decision_text = "License Agreement Accepted"
            
            send_reply_confirmation_email(
                original_sender_email=submission.email,
                submission_id=submission.id,
                decision_text=decision_text,
                reply_channel_address=reply_to_address,
                submission_token=submission.acceptance_token
            )
            current_app.logger.info(f"Sent link-based acceptance confirmation email for submission {submission.id}")
        except Exception as e_email:
            current_app.logger.error(f"Failed to send link-based acceptance confirmation for submission {submission.id}: {e_email}", exc_info=True)
            # Do not fail the whole request if the email fails, but log it.

        success_message = "Thank you for accepting the license for your submission!"
        if request.method == 'GET':
            return render_template('acceptance_thank_you.html', submission=submission, message=success_message)
        else: # For POST requests or other API uses
            return jsonify({"status": "success", "message": success_message})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error in accept_license for submission {submission.id if submission else 'unknown'}: {e}", exc_info=True)
        error_message = 'An error occurred while processing your acceptance. Please try again or contact support.'
        if request.method == 'GET':
            # Clear any existing messages before setting the error message
            session.pop('_flashes', None)
            flash(error_message, 'danger')
            return redirect(url_for('training_data')) # Or a generic error page
        else:
            return jsonify({"status": "error", "message": f"Database error: {str(e)}"}), 500

@app.route('/api/decline-license/<token>', methods=['GET'])
def decline_license(token):
    """Handle license declining via email link for a Submission."""
    submission = Submission.query.filter_by(acceptance_token=token).first_or_404()

    if submission.acceptance_state != AcceptanceState.PENDING:
        if submission.acceptance_state == AcceptanceState.DECLINED:
            return render_template('decline_confirmation.html', message="This submission has already been declined.")
        elif submission.acceptance_state == AcceptanceState.ACCEPTED:
            return render_template('acceptance_thank_you.html', message="This submission has already been accepted and cannot be declined. You may withdraw it if needed.")
        # Fallback redirect for any other state, though unlikely.
        return redirect(url_for('home'))

    submission.acceptance_state = AcceptanceState.DECLINED
    submission.accepted_at = datetime.utcnow() # Using accepted_at to mark when the decision was made
    submission.acceptance_method = 'link'
    
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error declining license for submission {submission.id}: {e}", exc_info=True)
        flash("An error occurred while processing your request. Please contact support.", 'danger')
        return redirect(url_for('home'))

    return render_template('decline_confirmation.html')

@app.route('/api/withdraw-submission/<token>', methods=['GET'])
def withdraw_submission(token):
    """Handle submission withdrawal via email link."""
    submission = Submission.query.filter_by(acceptance_token=token).first_or_404()

    if submission.is_withdrawn:
        return render_template('withdrawal_confirmation.html', message="This submission has already been withdrawn.")

    submission.is_withdrawn = True
    submission.withdrawn_at = datetime.utcnow()
    
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error withdrawing submission {submission.id}: {e}", exc_info=True)
        flash("An error occurred while processing your request. Please contact support.", 'danger')
        return redirect(url_for('home'))
        
    return render_template('withdrawal_confirmation.html')

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

@app.route('/training-data-stats')
@cache.cached(timeout=900)  # Cache for 15 minutes
def training_data_stats():
    # Get all non-withdrawn submissions with their builds and screenshots
    submissions = Submission.query.options(
        db.joinedload(Submission.builds).joinedload(Build.screenshots)
    ).filter(Submission.is_withdrawn == False).all()
    
    # Initialize stats
    stats = {
        'total_submissions': 0,
        'total_accepted': 0,
        'total_declined': 0,
        'total_pending': 0,
        'total_screenshots': 0,
        'by_screenshot_type': {  # Renamed for clarity
            'space': {'total': 0, 'accepted': 0},
            'ground': {'total': 0, 'accepted': 0}
        },
        'by_platform_type': {
            'PC': {
                'space': {'total_builds': 0, 'accepted_builds': 0, 'total_screenshots': 0, 'accepted_screenshots': 0},
                'ground': {'total_builds': 0, 'accepted_builds': 0, 'total_screenshots': 0, 'accepted_screenshots': 0}
            },
            'Console': {
                'space': {'total_builds': 0, 'accepted_builds': 0, 'total_screenshots': 0, 'accepted_screenshots': 0},
                'ground': {'total_builds': 0, 'accepted_builds': 0, 'total_screenshots': 0, 'accepted_screenshots': 0}
            }
        },
        'target_per_platform_type': 75, # Target number of builds for each platform/type combo
        'target_per_label': 50,         # Target number of screenshots for each label (space/ground)
    }
    
    # Process submissions
    for submission in submissions:
        stats['total_submissions'] += 1
        if submission.acceptance_state == AcceptanceState.ACCEPTED:
            stats['total_accepted'] += 1
        elif submission.acceptance_state == AcceptanceState.DECLINED:
            stats['total_declined'] += 1
        else: # PENDING
            stats['total_pending'] += 1
        
        for build in submission.builds:
            # Ensure platform and type are valid keys
            platform_key = build.platform if build.platform in stats['by_platform_type'] else None
            type_key = build.type if platform_key and build.type in stats['by_platform_type'][platform_key] else None

            if platform_key and type_key:
                stats['by_platform_type'][platform_key][type_key]['total_builds'] += 1
                if submission.acceptance_state == AcceptanceState.ACCEPTED:
                    stats['by_platform_type'][platform_key][type_key]['accepted_builds'] += 1

            for screenshot in build.screenshots:
                stats['total_screenshots'] += 1
                # Stats for screenshot types (labels), derived from build
                # Ensure build relationship is loaded. The query in training_data_stats should handle this.
                # Submission.query.options(db.joinedload(Submission.builds).joinedload(Build.screenshots))
                if screenshot.build and screenshot.build.type in stats['by_screenshot_type']:
                    stats['by_screenshot_type'][screenshot.build.type]['total'] += 1
                    if submission.acceptance_state == AcceptanceState.ACCEPTED:
                        stats['by_screenshot_type'][screenshot.build.type]['accepted'] += 1
                
                # Aggregate screenshot counts within platform/type as well
                if platform_key and type_key:
                    stats['by_platform_type'][platform_key][type_key]['total_screenshots'] += 1
                    if submission.acceptance_state == AcceptanceState.ACCEPTED:
                        stats['by_platform_type'][platform_key][type_key]['accepted_screenshots'] += 1
    
    # Ensure by_type is a standard dict for the template, which it already is now
    # No conversion needed if initialized as a dict with predefined keys
    
    return render_template('training_data_stats.html', 
                         stats=stats, 
                         now=datetime.utcnow(),
                         active_page='training_data_stats')

@app.route('/acceptance-thank-you')
def acceptance_thank_you():
    # This page is rendered dynamically by the accept_license route.
    # A direct link here doesn't make sense without submission context.
    # If a generic thank you is needed, it should be a static page or have logic.
    # For now, redirecting to home to avoid errors from missing template/context.
    return redirect(url_for('home'))


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    form = LoginForm()
    if form.validate_on_submit():
        user = AdminUser.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data) and not user.is_locked:
            session['admin_user_id'] = user.id
            session.permanent = True  # honour PERMANENT_SESSION_LIFETIME
            flash('Logged in as admin.', 'success')
            next_page = request.args.get('next')
            if not next_page or not is_safe_url(next_page):
                next_page = url_for('browse_screenshots')
            return redirect(next_page)
        flash('Invalid credentials', 'danger')
    return render_template('admin_login.html', form=form, active_page='admin_login')


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_user_id', None)
    flash('Logged out.', 'info')
    return redirect(url_for('home'))


@app.route('/admin')
def admin_dashboard():
    if not is_admin():
        return redirect(url_for('admin_login', next=request.path))
    return render_template('admin_dashboard.html', active_page='admin_dashboard')


@app.route('/admin/users', methods=['GET', 'POST'])
def admin_users():
    if not is_admin():
        return redirect(url_for('admin_login', next=request.path))
    
    form = AdminUserForm()
    if form.validate_on_submit():
        new_user = AdminUser(username=form.username.data)
        new_user.set_password(form.password.data)
        db.session.add(new_user)
        db.session.commit()
        flash(f'Admin user {new_user.username} created successfully.', 'success')
        return redirect(url_for('admin_users'))

    users = AdminUser.query.order_by(AdminUser.username).all()
    return render_template('admin_users.html', users=users, form=form, active_page='admin_users')


@app.route('/admin/user/<int:user_id>/change-password', methods=['GET', 'POST'])
def change_admin_password(user_id):
    if not is_admin():
        return redirect(url_for('admin_login'))
    
    user = AdminUser.query.get_or_404(user_id)
    form = ChangePasswordForm()
    
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash(f"Password for user {user.username} has been updated.", 'success')
        return redirect(url_for('admin_users'))
        
    return render_template('admin_change_password.html', user=user, form=form, active_page='admin_users')

@app.route('/admin/user/<int:user_id>/lock', methods=['POST'])
def lock_admin_user(user_id):
    if not is_admin():
        return redirect(url_for('admin_login'))
    user_to_lock = AdminUser.query.get_or_404(user_id)
    if user_to_lock.id == session['admin_user_id']:
        flash("You cannot lock your own account.", 'danger')
    else:
        user_to_lock.is_locked = True
        db.session.commit()
        flash(f"User {user_to_lock.username} has been locked.", 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/user/<int:user_id>/unlock', methods=['POST'])
def unlock_admin_user(user_id):
    if not is_admin():
        return redirect(url_for('admin_login'))
    user_to_unlock = AdminUser.query.get_or_404(user_id)
    user_to_unlock.is_locked = False
    db.session.commit()
    flash(f"User {user_to_unlock.username} has been unlocked.", 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
def delete_admin_user(user_id):
    if not is_admin():
        flash("You do not have permission to perform this action.", "danger")
        return redirect(url_for('admin_login'))

    user_to_delete = AdminUser.query.get_or_404(user_id)
    
    # Prevent the user from deleting their own account
    if user_to_delete.id == session.get('admin_user_id'):
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for('admin_users'))
    
    db.session.delete(user_to_delete)
    db.session.commit()
    flash(f"User '{user_to_delete.username}' has been deleted.", "success")
    return redirect(url_for('admin_users'))


@app.route('/admin/screenshots')
def browse_screenshots():
    if not is_admin():
        return redirect(url_for('admin_login', next=request.path))
    return render_template('admin_screenshots.html', active_page='admin_screenshots')


@app.route('/admin/api/screenshots')
def admin_screenshots_data():
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 403

    # Eager load related data to avoid N+1 queries
    submissions = Submission.query.options(
        db.joinedload(Submission.builds).joinedload(Build.screenshots),
        db.joinedload(Submission.email_logs),
        db.joinedload(Submission.link_logs)
    ).order_by(Submission.created_at.desc()).all()

    data_structured = {}
    for sub in submissions:
        if not sub.builds:
            continue
        
        # Events are at the submission level, so we prepare them once.
        events = []
        events.append({"type": "Submitted", "timestamp": sub.created_at.isoformat(), "method": "Web Form"})
        
        # Helper to find the log associated with an event
        def find_log_for_event(timestamp, method):
            if method == 'link':
                # Find the link log closest in time
                return min(sub.link_logs, key=lambda log: abs(log.clicked_at - timestamp), default=None)
            elif method == 'email':
                # Find the email log closest in time
                return min(sub.email_logs, key=lambda log: abs(log.received_at - timestamp), default=None)
            return None

        if sub.acceptance_state == AcceptanceState.ACCEPTED and sub.accepted_at:
            log = find_log_for_event(sub.accepted_at, sub.acceptance_method)
            details = {}
            if log:
                if sub.acceptance_method == 'link':
                    details = {"log_id": log.id, "details": {"ip_address": log.ip_address, "user_agent": log.user_agent}}
                elif sub.acceptance_method == 'email':
                    details = {"log_id": log.id, "details": {"subject": log.subject, "from": log.from_address}}
            events.append({"type": "Accepted", "timestamp": sub.accepted_at.isoformat(), "method": sub.acceptance_method.capitalize(), **details})
        
        elif sub.acceptance_state == AcceptanceState.DECLINED and sub.accepted_at:
            log = find_log_for_event(sub.accepted_at, sub.acceptance_method)
            details = {}
            if log:
                if sub.acceptance_method == 'link':
                    details = {"log_id": log.id, "details": {"ip_address": log.ip_address, "user_agent": log.user_agent}}
                elif sub.acceptance_method == 'email':
                    details = {"log_id": log.id, "details": {"subject": log.subject, "from": log.from_address}}
            events.append({"type": "Declined", "timestamp": sub.accepted_at.isoformat(), "method": sub.acceptance_method.capitalize(), **details})

        if sub.is_withdrawn and sub.withdrawn_at:
            # Withdrawals are always via link
            log = find_log_for_event(sub.withdrawn_at, 'link')
            details = {}
            if log:
                details = {"log_id": log.id, "details": {"ip_address": log.ip_address, "user_agent": log.user_agent}}
            events.append({"type": "Withdrawn", "timestamp": sub.withdrawn_at.isoformat(), "method": "Link", **details})

        # Add other general email events that are not the deciding event
        for log in sub.email_logs:
            is_decision_log = (sub.accepted_at and abs(log.received_at - sub.accepted_at) < timedelta(seconds=10))
            if not is_decision_log:
                 events.append({"type": "Email Received", "timestamp": log.received_at.isoformat(), "method": "Email", "log_id": log.id, "details": {"subject": log.subject, "from": log.from_address}})

        events.sort(key=lambda x: datetime.fromisoformat(x['timestamp'].replace('Z', '+00:00')))

        # Now, iterate over all builds within the submission
        for build in sub.builds:
            platform = build.platform or "Unknown"
            sc_type = build.type or "Unknown"

            screenshots_info = [{
                'id': sc.id,
                'filename': sc.filename,
                'build_id': str(build.id),
                'submission_id': str(sub.id),
                'submission_created': sub.created_at.isoformat(),
                'is_accepted': sub.is_accepted,
                'acceptance_state': sub.acceptance_state.value,
                'is_withdrawn': sub.is_withdrawn,
                'email': sub.email,
                'events': events
            } for sc in build.screenshots]

            if not screenshots_info:
                continue

            date_str = sub.created_at.strftime('%Y-%m-%d')
            data_structured.setdefault(platform, {}).setdefault(sc_type, {}).setdefault(date_str, []).extend(screenshots_info)
        
    return jsonify(data_structured)


@app.route('/admin/api/screenshot_info/<int:screenshot_id>')
def admin_screenshot_info(screenshot_id):
    if not is_admin():
        return jsonify({'error': 'unauthorized'}), 403
    sc = Screenshot.query.get_or_404(screenshot_id)
    submission = sc.build.submission
    info = {
        'id': sc.id,
        'filename': sc.filename,
        'is_accepted': submission.is_accepted,
        'acceptance_state': submission.acceptance_state.name.lower() if submission.acceptance_state else None,
        'is_withdrawn': submission.is_withdrawn,
    }
    return jsonify(info)


@app.route('/admin/api/email_log/<log_id>')
def get_email_log(log_id):
     if not is_admin():
         return jsonify({"error": "Unauthorized"}), 403
     
     log = EmailLog.query.get_or_404(log_id)
     
     return jsonify({
         "from": log.from_address,
         "to": log.to_address,
         "subject": log.subject,
         "body_html": log.body_html,
         "body_text": log.body_text,
         "received_at": log.received_at.isoformat(),
         "headers": json.loads(log.headers_json) if log.headers_json else {}
     })


@app.route('/admin/screenshot/<int:screenshot_id>')
def admin_screenshot_image(screenshot_id):
    if not is_admin():
        return "Unauthorized", 403
    sc = Screenshot.query.get_or_404(screenshot_id)
    mime = 'image/png' if sc.filename.lower().endswith('png') else 'image/jpeg'
    if sc.data:
        return send_file(BytesIO(sc.data), mimetype=mime)
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], sc.filename)
    return send_file(file_path, mimetype=mime)


# Webhook endpoint for handling email replies
@app.route('/api/email-webhook', methods=['GET', 'POST'])
@csrf.exempt
def handle_email_reply():
    """Handle email replies from ForwardEmail for Submissions."""
    if request.method == 'GET':
        # ForwardEmail webhook verification often uses GET for initial setup
        return jsonify({"status": "ok, webhook alive"})
    
    # Get the webhook secret key from environment
    webhook_secret = os.getenv('FORWARD_EMAIL_WEBHOOK_SECRET')
    if not webhook_secret:
        current_app.logger.error("Email webhook: FORWARD_EMAIL_WEBHOOK_SECRET not configured")
        return jsonify({"status": "error", "message": "Server configuration error"}), 500
    
    # Verify the request IP is one of ForwardEmail's MX servers
    client_ip = request.remote_addr
    allowed_ips = get_forwardemail_ips()
    if allowed_ips and client_ip not in allowed_ips:
        current_app.logger.warning(
            f"Email webhook: Rejected request from unauthorized IP '{client_ip}'"
        )
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    
    # Verify webhook signature
    signature_header = request.headers.get('X-Webhook-Signature')
    if not signature_header:
        current_app.logger.warning("Email webhook: Missing X-Webhook-Signature header")
        return jsonify({"status": "error", "message": "Missing signature"}), 400
    
    # Get raw request data for signature verification
    request_data = request.get_data()
    
    current_app.logger.info("Email webhook: Verifying signature...")
    current_app.logger.debug(f"Email webhook: Signature header: {signature_header}")

    if not verify_webhook_signature(request_data, signature_header, webhook_secret):
        current_app.logger.warning(f"Email webhook: Invalid webhook signature. Verification failed for IP: {client_ip}")
        # For debugging, let's log the data used for verification
        current_app.logger.debug(f"Email webhook: Data used for signature verification: {request_data.decode('utf-8', errors='ignore')}")
        return jsonify({"status": "error", "message": "Invalid signature"}), 401
    
    current_app.logger.info("Email webhook: Signature verified successfully.")

    try:
        # Now that signature is verified, parse the JSON data
        try:
            data = json.loads(request_data)
        except json.JSONDecodeError as e:
            current_app.logger.error(f"Email webhook: Failed to parse JSON data after signature verification: {e}")
            return jsonify({"status": "error", "message": "Invalid JSON data"}), 400
        
        # --- START: Debugging Email Parsing --- 
        current_app.logger.info(f"Email webhook: Debug - Raw 'from' field: {data.get('from')}")
        current_app.logger.info(f"Email webhook: Debug - Raw 'to' field: {data.get('to')}")
        current_app.logger.info(f"Email webhook: Debug - Raw 'envelopeRecipients' field: {data.get('envelopeRecipients')}")
        # --- END: Debugging Email Parsing ---
        
        # --- START: Enhanced Header and Email Info Extraction ---
        # The 'headers' in the payload body is a dict, not a list of dicts.
        all_headers_raw = data.get('headers', {})
        headers_json_str = json.dumps(all_headers_raw) if all_headers_raw else None
        
        headers_dict = {k.lower(): v for k, v in all_headers_raw.items()}

        message_id_value = headers_dict.get('message-id')

        # Robustly parse 'from' address
        from_email_address = None
        from_field_data = data.get('from')
        if isinstance(from_field_data, str):
            from_email_address = from_field_data.lower()
        elif isinstance(from_field_data, dict):
            from_value_list = from_field_data.get('value')
            if isinstance(from_value_list, list) and from_value_list:
                sender_obj = from_value_list[0]
                if isinstance(sender_obj, dict):
                    from_email_address = sender_obj.get('address', '').lower() or sender_obj.get('email', '').lower()

        if not from_email_address:
            current_app.logger.warning(f"Email webhook: Could not parse 'from_email_address' from 'from' field: {from_field_data}")

        # Robustly parse 'to' address
        to_email_address = None
        envelope_recipients = data.get('envelopeRecipients', []) 
        if isinstance(envelope_recipients, list) and envelope_recipients and isinstance(envelope_recipients[0], str):
            to_email_address = envelope_recipients[0].lower()
        
        if not to_email_address:
            to_field_data = data.get('to')
            if isinstance(to_field_data, str):
                to_email_address = to_field_data.lower()
            elif isinstance(to_field_data, dict):
                to_value_list = to_field_data.get('value')
                if isinstance(to_value_list, list) and to_value_list:
                    recipient_obj = to_value_list[0]
                    if isinstance(recipient_obj, dict):
                        to_email_address = recipient_obj.get('address', '').lower() or recipient_obj.get('email', '').lower()
        
        if not to_email_address:
            current_app.logger.warning(f"Email webhook: Could not parse 'to_email_address' from 'envelopeRecipients' or 'to' field. Envelope: {envelope_recipients}, To: {data.get('to')}")
        # --- END: Enhanced Header and Email Info Extraction ---
        
        submission_id = None
        
        username_param = request.args.get('username', '')
        current_app.logger.info(f"Email webhook: Extracted username from query params: '{username_param}'")
        if username_param.startswith('training-data-submission-'):
            try:
                submission_id = username_param.split('training-data-submission-')[-1]
                current_app.logger.info(f"Email webhook: Extracted submission_id from username: '{submission_id}'")
            except (IndexError, ValueError) as e:
                current_app.logger.warning(f"Email webhook: Error extracting submission_id from username '{username_param}': {e}")
                submission_id = None

        if not submission_id:
            submission_id_from_header = headers_dict.get('x-sister-submission-id')
            if submission_id_from_header:
                submission_id = submission_id_from_header
                current_app.logger.info(f"Email webhook: Extracted submission_id from header 'X-SISTER-Submission-ID': '{submission_id}'")

        if not submission_id:
            current_app.logger.warning(f"Email webhook: Could not determine submission_id. From/To/Subject/MsgID: {from_email_address}/{to_email_address}/{data.get('subject')}/{message_id_value}")
            return jsonify({"status": "error", "message": "Could not identify submission from email reply."}), 400
            
        # Check if submission exists in database
        submission = Submission.query.get(submission_id)
        if not submission:
            current_app.logger.warning(f"Email webhook: Submission with ID '{submission_id}' not found in database.")
            return jsonify({"status": "error", "message": f"Submission {submission_id} not found."}), 404

        email_text_content = data.get('text', '')
        email_subject = data.get('subject', '')
        
        current_app.logger.info(f"Email webhook: Processing reply for submission_id='{submission_id}', from='{from_email_address}', to='{to_email_address}', subject='{email_subject}', msg_id='{message_id_value}'")

        reply_only_text = extract_reply_text(email_text_content)
        current_app.logger.info(f"Email webhook: Extracted reply-only text (first 200 chars): '{reply_only_text[:200]}...' (length: {len(reply_only_text)})")

        acceptance_keywords = ['accept', 'confirm', 'yes', 'agree', 'consent']
        disagreement_keywords = ['disagree', 'decline']
        withdrawal_keywords = ['withdraw']

        reply_lower = reply_only_text.lower()
        is_acceptance_in_reply = any(keyword in reply_lower for keyword in acceptance_keywords)
        is_disagreement_in_reply = any(keyword in reply_lower for keyword in disagreement_keywords)
        is_withdrawal_in_reply = any(keyword in reply_lower for keyword in withdrawal_keywords)

        current_app.logger.info(f"Email webhook: Decision check for submission_id='{submission_id}': acceptance='{is_acceptance_in_reply}', disagreement='{is_disagreement_in_reply}', withdrawal='{is_withdrawal_in_reply}'")
        
        decision_for_email = "Reply Received - No explicit decision keywords detected" # Default
        action_taken = False

        # Priority: Withdrawal > Disagreement > Agreement
        if is_withdrawal_in_reply:
            submission_to_withdraw = Submission.query.get(submission_id)
            if not submission_to_withdraw:
                 current_app.logger.warning(f"Email webhook: Submission with ID '{submission_id}' not found for withdrawal.")
                 return jsonify({"status": "error", "message": f"Submission {submission_id} not found."}), 404
            
            if submission_to_withdraw.is_withdrawn:
                current_app.logger.info(f"Email webhook: Submission '{submission_id}' already withdrawn.")
                return jsonify({"status": "info", "message": f"Submission {submission_id} already withdrawn."}), 200

            submission_to_withdraw.is_withdrawn = True
            submission_to_withdraw.withdrawn_at = datetime.utcnow()
            decision_for_email = "Submission Withdrawn"
            
            try:
                db.session.commit()
                current_app.logger.info(f"Email webhook: Successfully marked submission '{submission_id}' as withdrawn.")
                email_sent_successfully = send_reply_confirmation_email(from_email_address, submission_id, decision_for_email, to_email_address)
                response_message = f"Submission {submission_id} has been withdrawn."
                if not email_sent_successfully:
                    response_message += " Confirmation email FAILED to send."
                return jsonify({"status": "success", "message": response_message}), 200
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Email webhook: DB error withdrawing submission '{submission_id}': {e}", exc_info=True)
                return jsonify({"status": "error", "message": "Database error during withdrawal."}), 500

        elif is_disagreement_in_reply:
            submission_to_decline = Submission.query.get(submission_id)
            if not submission_to_decline:
                current_app.logger.warning(f"Email webhook: Submission with ID '{submission_id}' not found for declining.")
                return jsonify({"status": "error", "message": f"Submission {submission_id} not found."}), 404

            if submission_to_decline.acceptance_state != AcceptanceState.PENDING:
                 current_app.logger.info(f"Email webhook: Submission '{submission_id}' already has state '{submission_to_decline.acceptance_state.value}'. Cannot decline.")
                 return jsonify({"status": "info", "message": f"Submission {submission_id} already processed."}), 200

            submission_to_decline.acceptance_state = AcceptanceState.DECLINED
            submission_to_decline.acceptance_method = 'email'
            submission_to_decline.accepted_at = datetime.utcnow() # Timestamp of decision

            decision_for_email = "License Agreement Declined (based on your reply)"
            
            try:
                db.session.commit()
                current_app.logger.info(f"Email webhook: Successfully marked submission '{submission_id}' as declined.")
                email_sent_successfully = send_reply_confirmation_email(from_email_address, submission_id, decision_for_email, to_email_address)
                response_message = f"Disagreement processed for submission {submission_id}. License declined."
                if not email_sent_successfully:
                    response_message += " Confirmation email FAILED to send."
                return jsonify({"status": "success", "message": response_message}), 200
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Email webhook: DB error declining submission '{submission_id}': {e}", exc_info=True)
                return jsonify({"status": "error", "message": "Database error during decline."}), 500

        elif is_acceptance_in_reply:
            submission_to_accept = Submission.query.get(submission_id)
            
            if not submission_to_accept:
                current_app.logger.warning(f"Email webhook: Submission with ID '{submission_id}' not found for acceptance.")
                return jsonify({"status": "error", "message": f"Submission {submission_id} not found."}), 404

            if submission_to_accept.acceptance_state != AcceptanceState.PENDING:
                 current_app.logger.info(f"Email webhook: Submission '{submission_id}' already has state '{submission_to_accept.acceptance_state.value}'. Cannot accept again.")
                 return jsonify({"status": "info", "message": f"Submission {submission_id} already processed."}), 200

            # Log the received email - This logic seems to be missing from the original disagreement block, let's keep it here for acceptance
            try:
                email_html_content = data.get('html', '')
                new_email_log = EmailLog(
                    submission_id=submission_to_accept.id,
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
                current_app.logger.info(f"Email webhook: Email log created for submission_id='{submission_to_accept.id}', message_id='{message_id_value}' to EmailLog ID {new_email_log.id}.")
            except Exception as e_log:
                db.session.rollback()
                current_app.logger.error(f"Email webhook: Failed to log email for submission_id='{submission_to_accept.id}': {e_log}", exc_info=True)
                # Continue processing acceptance even if logging failed

            submission_to_accept.acceptance_state = AcceptanceState.ACCEPTED
            submission_to_accept.accepted_at = datetime.utcnow()
            submission_to_accept.acceptance_method = 'email'

            try:
                db.session.commit()
                current_app.logger.info(f"Email webhook: Successfully accepted Submission '{submission_id}' via email reply.")
                decision_for_email = "License Agreement Accepted"
                email_sent_successfully = send_reply_confirmation_email(
                    from_email_address, 
                    submission_id, 
                    decision_for_email, 
                    to_email_address,
                    submission_token=submission_to_accept.acceptance_token # Pass token for withdrawal link
                )
                response_message = f"Submission {submission_id} accepted via email."
                if not email_sent_successfully:
                    response_message += " Acceptance confirmation email FAILED to send."
                return jsonify({"status": "success", "message": response_message}), 200
            except Exception as e_commit:
                db.session.rollback()
                current_app.logger.error(f"Email webhook: Database error committing acceptance for submission_id '{submission_id}': {e_commit}", exc_info=True)
                return jsonify({"status": "error", "message": "Database error during acceptance."}), 500
        else:
            current_app.logger.info(f"Email webhook: No decision keywords found for submission_id='{submission_id}'.")
            decision_for_email = "Reply Received - No explicit decision keywords detected"
            email_sent_successfully = send_reply_confirmation_email(from_email_address, submission_id, decision_for_email, to_email_address)
            response_message = "No decision keywords found. Reply logged."
            if not email_sent_successfully:
                 response_message += " Neutral confirmation email FAILED to send."
            return jsonify({"status": "info", "message": response_message}), 200

    except Exception as e:
        current_app.logger.error(f"Email webhook: General error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "An internal error occurred."}), 500

@app.route('/admin/api/resend-consent/<submission_id>', methods=['POST'])
def resend_consent_email(submission_id):
    if not is_admin():
        return jsonify({'error': 'unauthorized'}), 403
    
    submission = Submission.query.get_or_404(submission_id)
    
    if submission.acceptance_state != AcceptanceState.PENDING:
        return jsonify({'error': f'Submission is already in "{submission.acceptance_state.value}" state.'}), 400
    
    # Generate a new acceptance token
    submission.acceptance_token = generate_acceptance_token(submission.id, submission.email)
    
    # Prepare consents for email
    consents_for_email = {
        'agreed_to_license': True  # The user must have agreed during the initial submission to get to this stage.
    }
    
    # Send consent email
    email_sent = send_consent_email(
        submission.email,
        submission.builds,
        consents_for_email,
        submission.acceptance_token,
        submission.id
    )
    
    if email_sent:
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Consent email resent successfully'})
    else:
        db.session.rollback()
        return jsonify({'error': 'Failed to send consent email'}), 500

@app.route('/admin/dataset-labels', methods=['GET', 'POST'])
def admin_dataset_labels():
    if not is_admin():
        return redirect(url_for('admin_login'))
    
    form = DatasetLabelForm()
    if form.validate_on_submit():
        new_label = DatasetLabel(name=form.name.data, description=form.description.data)
        db.session.add(new_label)
        db.session.commit()
        flash('Dataset label created successfully.', 'success')
        return redirect(url_for('admin_dataset_labels'))
    
    labels = DatasetLabel.query.order_by(DatasetLabel.name).all()
    return render_template('admin/dataset_labels.html', form=form, labels=labels, title="Manage Dataset Labels")

@app.route('/admin/dataset-labels/edit/<int:label_id>', methods=['GET', 'POST'])
def edit_dataset_label(label_id):
    if not is_admin():
        return redirect(url_for('admin_login'))
    
    label = DatasetLabel.query.get_or_404(label_id)
    form = DatasetLabelForm(obj=label)

    # Custom validation to allow saving with the same name
    if request.method == 'POST':
        # Temporarily remove the validator if the name hasn't changed
        original_name = label.name
        if form.name.data == original_name:
            form.name.validators = [v for v in form.name.validators if v.__class__.__name__ != 'validate_name']

    if form.validate_on_submit():
        label.name = form.name.data
        label.description = form.description.data
        db.session.commit()
        flash('Dataset label updated successfully.', 'success')
        return redirect(url_for('admin_dataset_labels'))
    
    return render_template('admin/edit_dataset_label.html', form=form, label=label, title="Edit Dataset Label")

@app.route('/admin/dataset-labels/toggle-active/<int:label_id>', methods=['POST'])
def toggle_dataset_label_active(label_id):
    if not is_admin():
        return jsonify({'error': 'Unauthorized'}), 403
    
    label = DatasetLabel.query.get_or_404(label_id)
    label.is_active = not label.is_active
    db.session.commit()
    return jsonify({'success': True, 'is_active': label.is_active})

@app.route('/admin/dataset-manager')
def dataset_manager():
    if not is_admin():
        return redirect(url_for('admin_login'))

    page = request.args.get('page', 1, type=int)
    per_page = 50 # Or get from request.args

    # Query for accepted builds
    builds_query = Build.query.join(Submission).filter(
        Submission.acceptance_state == AcceptanceState.ACCEPTED
    )

    builds_pagination = builds_query.paginate(page=page, per_page=per_page, error_out=False)
    
    active_labels = DatasetLabel.query.filter_by(is_active=True).order_by(DatasetLabel.name).all()

    return render_template(
        'admin/dataset_manager.html',
        builds=builds_pagination.items,
        pagination=builds_pagination,
        labels=active_labels,
        title="Dataset Manager"
    )

@app.route('/admin/api/builds/<build_id>/set-label', methods=['POST'])
def set_build_dataset_label(build_id):
    if not is_admin():
        return jsonify({'error': 'Unauthorized'}), 403

    build = Build.query.get_or_404(build_id)
    data = request.get_json()
    label_id = data.get('label_id')

    if label_id:
        label = DatasetLabel.query.get(label_id)
        if not label or not label.is_active:
            return jsonify({'error': 'Invalid or inactive label'}), 400
        build.dataset_label_id = label_id
    else:
        build.dataset_label_id = None
    
    db.session.commit()
    return jsonify({'success': True, 'label_id': build.dataset_label_id})

# ────────────────────────────────────────────────────────────────────────────────
# Global response hardening
# ────────────────────────────────────────────────────────────────────────────────

# Add common security headers to all responses
@app.after_request
def set_security_headers(resp):
    resp.headers.setdefault('X-Frame-Options', 'DENY')
    resp.headers.setdefault('Content-Security-Policy', "default-src 'self'")
    return resp

# Invalidate admin sessions if the user no longer exists or is locked
@app.before_request
def verify_admin_session():
    admin_id = session.get('admin_user_id')
    if admin_id is not None:
        user = AdminUser.query.get(admin_id)
        if not user or user.is_locked:
            session.pop('admin_user_id', None)
            flash('Please log in again.', 'warning')
            if request.path.startswith('/admin'):
                return redirect(url_for('admin_login', next=request.path))

