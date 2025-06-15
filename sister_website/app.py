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
    make_response,
)
from flask_migrate import Migrate
from flask_caching import Cache
from flask_wtf import CSRFProtect
from urllib.parse import urlparse, urljoin
import uuid  # Ensure uuid is imported for new models
import magic
import re
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
from io import BytesIO
import requests
from sqlalchemy import or_
from sqlalchemy import case, func, and_
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from itsdangerous import URLSafeTimedSerializer as Serializer
from PIL import Image

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
    BuildAuditLog,
    User
)
from .forms import UploadForm, AdminLoginForm, AdminUserForm, ChangePasswordForm, DatasetLabelForm, RegistrationForm, UserLoginForm, ForgotPasswordForm, ResetPasswordForm, UserSettingsForm
from .email_utils import (
    send_consent_email,
    send_reply_confirmation_email,
    verify_webhook_signature,
    send_verification_email,
    send_password_reset_email
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
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
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

    # Add ProxyFix to handle headers from a reverse proxy
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

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

@app.cli.command('generate-thumbnails')
def generate_thumbnails_command():
    """Generate thumbnails for existing screenshots that don't have them."""
    with app.app_context():
        # Query screenshots that don't have thumbnails
        try:
            screenshots = Screenshot.query.filter(
                or_(Screenshot.thumbnail_data == None, Screenshot.thumbnail_data == b'')
            ).all()
        except Exception:
            # If thumbnail_data field doesn't exist yet, skip this command
            print("thumbnail_data field doesn't exist yet. Run database migration first.")
            return
            
        if not screenshots:
            print("No screenshots found that need thumbnails.")
            return
            
        print(f"Generating thumbnails for {len(screenshots)} screenshots...")
        
        success_count = 0
        error_count = 0
        
        for screenshot in screenshots:
            if not screenshot.data:
                print(f"Skipping screenshot {screenshot.id}: no image data")
                continue
                
            thumbnail_data = generate_screenshot_thumbnail(screenshot.data)
            if thumbnail_data:
                screenshot.thumbnail_data = thumbnail_data
                success_count += 1
                print(f"Generated thumbnail for screenshot {screenshot.id} ({screenshot.filename})")
            else:
                error_count += 1
                print(f"Failed to generate thumbnail for screenshot {screenshot.id} ({screenshot.filename})")
        
        try:
            db.session.commit()
            print(f"Successfully generated {success_count} thumbnails, {error_count} errors.")
        except Exception as e:
            db.session.rollback()
            print(f"Error saving thumbnails to database: {e}")
            return

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
    """Saves a screenshot file, calculates its MD5, generates a thumbnail, and creates a Screenshot record in memory without saving to disk."""
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

        # Generate thumbnail using the utility function
        thumbnail_data = generate_screenshot_thumbnail(file_content)
        if thumbnail_data:
            current_app.logger.info(f"Generated thumbnail for {filename}: {len(thumbnail_data)} bytes")
        else:
            current_app.logger.warning(f"Failed to generate thumbnail for {filename}")
            # Continue without thumbnail - it's not critical

        # Create screenshot record, handling the case where thumbnail_data field might not exist yet
        screenshot_kwargs = {
            'filename': filename,
            'md5sum': md5_hash,
            'data': file_content,
        }
        
        # Only add thumbnail_data if the field exists in the model
        try:
            # Try to create a test instance to check if thumbnail_data field exists
            Screenshot()
            if hasattr(Screenshot, 'thumbnail_data'):
                screenshot_kwargs['thumbnail_data'] = thumbnail_data
        except Exception:
            pass  # Field might not exist yet, that's fine
            
        new_screenshot = Screenshot(**screenshot_kwargs)
        return new_screenshot
    except Exception as e:
        current_app.logger.error(f"Error processing screenshot data for {filename}: {e}")
        return None

def generate_acceptance_token(submission_id, email):
    """Generate a secure token for email acceptance for a Submission"""
    secret = current_app.config['SECRET_KEY']
    message = f"{submission_id}:{email}".encode('utf-8')
    return hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()

def generate_screenshot_thumbnail(screenshot_data):
    """Generate a thumbnail from screenshot data. Returns thumbnail bytes or None."""
    try:
        with Image.open(BytesIO(screenshot_data)) as img:
            # Convert to RGB if necessary (handles RGBA, P mode, etc.)
            if img.mode in ('RGBA', 'LA', 'P'):
                # Create a white background for transparent images
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Create thumbnail (240x240 max, maintaining aspect ratio)
            img.thumbnail((240, 240), Image.Resampling.LANCZOS)
            
            # Save thumbnail as JPEG to BytesIO
            thumbnail_buffer = BytesIO()
            img.save(thumbnail_buffer, format='JPEG', quality=85, optimize=True)
            return thumbnail_buffer.getvalue()
            
    except Exception as e:
        current_app.logger.error(f"Error generating thumbnail: {e}")
        return None

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
    # Pre-fill email field if user is logged in
    if current_user.is_authenticated:
        form.email.data = current_user.email
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
    """Handle license acceptance via email link (GET) or dashboard button (POST)."""
    submission = Submission.query.filter_by(acceptance_token=token).first()

    if not submission:
        message = "Invalid or expired acceptance link."
        if request.method == 'GET':
            flash(message, 'danger')
            return redirect(url_for('home'))
        else:
            return jsonify({"status": "error", "message": message}), 400

    # For dashboard actions, ensure the logged-in user is the owner
    if request.method == 'POST' and current_user.is_authenticated:
        if submission.email != current_user.email:
            return jsonify({"status": "error", "message": "Unauthorized"}), 403

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

@app.route('/api/decline-license/<token>', methods=['GET', 'POST'])
def decline_license(token):
    """Handle license declining via email link (GET) or dashboard button (POST)."""
    submission = Submission.query.filter_by(acceptance_token=token).first_or_404()

    # For dashboard actions, ensure the logged-in user is the owner
    if request.method == 'POST' and current_user.is_authenticated:
        if submission.email != current_user.email:
            return jsonify({"status": "error", "message": "Unauthorized"}), 403

    if submission.acceptance_state != AcceptanceState.PENDING:
        message = "This submission has already been processed and cannot be changed."
        if request.method == 'GET':
            return render_template('decline_confirmation.html', message=message)
        else:
            return jsonify({"status": "error", "message": message}), 409

    submission.acceptance_state = AcceptanceState.DECLINED
    submission.accepted_at = datetime.utcnow() # Using accepted_at to mark when the decision was made
    submission.acceptance_method = 'link'
    
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error declining license for submission {submission.id}: {e}", exc_info=True)
        if request.method == 'GET':
            flash("An error occurred while processing your request. Please contact support.", 'danger')
            return redirect(url_for('home'))
        else:
            return jsonify({"status": "error", "message": "Database error"}), 500

    if request.method == 'GET':
        return render_template('decline_confirmation.html')
    else:
        return jsonify({"status": "success", "message": "Submission declined."})

@app.route('/api/withdraw-submission/<token>', methods=['GET', 'POST'])
def withdraw_submission(token):
    """Handle submission withdrawal via email link (GET) or dashboard button (POST)."""
    submission = Submission.query.filter_by(acceptance_token=token).first_or_404()

    # For dashboard actions, ensure the logged-in user is the owner
    if request.method == 'POST' and current_user.is_authenticated:
        if submission.email != current_user.email:
            return jsonify({"status": "error", "message": "Unauthorized"}), 403

    if submission.is_withdrawn:
        message = "This submission has already been withdrawn."
        if request.method == 'GET':
            return render_template('withdrawal_confirmation.html', message=message)
        else:
            return jsonify({"status": "info", "message": message}), 200

    submission.is_withdrawn = True
    submission.withdrawn_at = datetime.utcnow()
    
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error withdrawing submission {submission.id}: {e}", exc_info=True)
        if request.method == 'GET':
            flash("An error occurred while processing your request. Please contact support.", 'danger')
            return redirect(url_for('home'))
        else:
            return jsonify({"status": "error", "message": "Database error"}), 500
        
    if request.method == 'GET':
        return render_template('withdrawal_confirmation.html')
    else:
        return jsonify({"status": "success", "message": "Submission withdrawn."})

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
    # --- Overview Stats ---
    # This query is still useful for high-level numbers and the progress bars.
    submissions = Submission.query.options(
        db.joinedload(Submission.builds).joinedload(Build.screenshots)
    ).filter(Submission.is_withdrawn == False).all()

    stats = {
        'total_submissions': len(submissions),
        'total_accepted': sum(1 for s in submissions if s.acceptance_state == AcceptanceState.ACCEPTED),
        'total_declined': sum(1 for s in submissions if s.acceptance_state == AcceptanceState.DECLINED),
        'total_pending': sum(1 for s in submissions if s.acceptance_state == AcceptanceState.PENDING),
        'total_screenshots': sum(len(b.screenshots) for s in submissions for b in s.builds),
        'by_platform_type': {
            'PC': {'space': {'total_builds': 0, 'accepted_builds': 0}, 'ground': {'total_builds': 0, 'accepted_builds': 0}},
            'Console': {'space': {'total_builds': 0, 'accepted_builds': 0}, 'ground': {'total_builds': 0, 'accepted_builds': 0}}
        },
        'target_per_platform_type': 75,
        'target_per_label': 50,
    }

    for sub in submissions:
        for build in sub.builds:
            if build.platform in stats['by_platform_type'] and build.type in stats['by_platform_type'][build.platform]:
                stats['by_platform_type'][build.platform][build.type]['total_builds'] += 1
                if sub.acceptance_state == AcceptanceState.ACCEPTED:
                    stats['by_platform_type'][build.platform][build.type]['accepted_builds'] += 1
    
    # --- Pivot Table Stats (via SQL) ---
    accepted_builds_subq = db.session.query(
        Build.dataset_label_id,
        Build.platform,
        Build.type
    ).join(Submission).filter(
        Submission.acceptance_state == AcceptanceState.ACCEPTED,
        Submission.is_withdrawn == False
    ).subquery()

    # Define the pivot columns using case statements
    pc_space = func.count(case((and_(accepted_builds_subq.c.platform == 'PC', accepted_builds_subq.c.type == 'space'), 1))).label('PC_space')
    pc_ground = func.count(case((and_(accepted_builds_subq.c.platform == 'PC', accepted_builds_subq.c.type == 'ground'), 1))).label('PC_ground')
    console_space = func.count(case((and_(accepted_builds_subq.c.platform == 'Console', accepted_builds_subq.c.type == 'space'), 1))).label('Console_space')
    console_ground = func.count(case((and_(accepted_builds_subq.c.platform == 'Console', accepted_builds_subq.c.type == 'ground'), 1))).label('Console_ground')

    # Main query to get all labels and their pivoted counts
    label_counts_results = db.session.query(
        DatasetLabel.id,
        DatasetLabel.name,
        DatasetLabel.is_active,
        pc_space,
        pc_ground,
        console_space,
        console_ground
    ).outerjoin(
        accepted_builds_subq, DatasetLabel.id == accepted_builds_subq.c.dataset_label_id
    ).group_by(
        DatasetLabel.id,
        DatasetLabel.name,
        DatasetLabel.is_active
    ).order_by(
        DatasetLabel.name
    ).all()

    # Reconstruct the pivot table structure for the template
    pivot_columns = ['PC_space', 'PC_ground', 'Console_space', 'Console_ground']
    label_pivot = {
        'rows': {},
        'column_totals': {col: 0 for col in pivot_columns},
        'grand_total': 0
    }

    for row in label_counts_results:
        row_total = row.PC_space + row.PC_ground + row.Console_space + row.Console_ground
        label_pivot['rows'][row.id] = {
            'name': row.name,
            'is_active': row.is_active,
            'counts': {
                'PC_space': row.PC_space,
                'PC_ground': row.PC_ground,
                'Console_space': row.Console_space,
                'Console_ground': row.Console_ground,
            },
            'row_total': row_total
        }
        # Aggregate totals
        label_pivot['column_totals']['PC_space'] += row.PC_space
        label_pivot['column_totals']['PC_ground'] += row.PC_ground
        label_pivot['column_totals']['Console_space'] += row.Console_space
        label_pivot['column_totals']['Console_ground'] += row.Console_ground
        label_pivot['grand_total'] += row_total

    stats['label_pivot'] = label_pivot
    
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
    form = AdminLoginForm()
    if form.validate_on_submit():
        user = AdminUser.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data) and not user.is_locked:
            session['admin_user_id'] = user.id
            session.permanent = True  # honour PERMANENT_SESSION_LIFETIME
            flash('Logged in as admin.', 'success')
            next_page = request.args.get('next')
            if not next_page or not is_safe_url(next_page):
                next_page = url_for('browse_submissions')
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


@app.route('/admin/submissions')
def browse_submissions():
    if not is_admin():
        return redirect(url_for('admin_login', next=request.path))
    
    build_id = request.args.get('build_id')
    
    return render_template('admin_submissions.html', active_page='admin_submissions', build_id=build_id)


@app.route('/admin/api/submissions')
def admin_submissions_data():
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 403

    # Eager load related data to avoid N+1 queries
    submissions = Submission.query.options(
        db.joinedload(Submission.builds).joinedload(Build.screenshots),
        db.joinedload(Submission.email_logs),
        db.joinedload(Submission.link_logs)
    ).order_by(Submission.created_at.desc()).all()

    data_flat = []
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

            for sc in build.screenshots:
                screenshot_info = {
                    'id': sc.id,
                    'filename': sc.filename,
                    'build_id': str(build.id),
                    'submission_id': str(sub.id),
                    'submission_created': sub.created_at.isoformat(),
                    'is_accepted': sub.is_accepted,
                    'acceptance_state': sub.acceptance_state.value,
                    'is_withdrawn': sub.is_withdrawn,
                    'email': sub.email,
                    'events': events,
                    'platform': platform,
                    'type': sc_type,
                    'date': sub.created_at.strftime('%Y-%m-%d')
                }
                data_flat.append(screenshot_info)
        
    return jsonify(data_flat)


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

@app.route('/admin/api/link_log/<log_id>')
def get_link_log(log_id):
     # This endpoint should only be available to admins.
     if not is_admin():
         return jsonify({"error": "Unauthorized"}), 403
     
     log = LinkLog.query.get_or_404(log_id)
     
     return jsonify({
         "ip_address": log.ip_address,
         "user_agent": log.user_agent,
         "clicked_at": log.clicked_at.isoformat(),
         "token_used": log.token_used
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

@app.route('/admin/screenshot/<int:screenshot_id>/thumbnail')
@cache.cached(timeout=900)  # Cache for 15 minutes
def admin_screenshot_thumbnail(screenshot_id):
    if not is_admin():
        return "Unauthorized", 403
    sc = Screenshot.query.get_or_404(screenshot_id)
    
    # Check if thumbnail_data field exists and has data
    if hasattr(sc, 'thumbnail_data') and sc.thumbnail_data:
        return send_file(BytesIO(sc.thumbnail_data), mimetype='image/jpeg')
    elif sc.data:
        # Generate thumbnail on-the-fly if not available
        thumbnail_data = generate_screenshot_thumbnail(sc.data)
        if thumbnail_data:
            return send_file(BytesIO(thumbnail_data), mimetype='image/jpeg')
        else:
            # Fallback to full image if thumbnail generation fails
            mime = 'image/png' if sc.filename.lower().endswith('png') else 'image/jpeg'
            return send_file(BytesIO(sc.data), mimetype=mime)
    else:
        return "No image data", 404


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
    return render_template('admin_dataset_labels.html', form=form, labels=labels, title="Manage Dataset Labels", active_page='admin_dataset_labels')

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
    
    return render_template('admin_edit_dataset_label.html', form=form, label=label, title="Edit Dataset Label", active_page='admin_dataset_labels')

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
    per_page = 50

    # Filter parameters
    build_id_filter = request.args.get('build_id', '')
    submission_id_filter = request.args.get('submission_id', '')
    submission_email_filter = request.args.get('submission_email', '')
    platform_filter = request.args.get('platform', '')
    type_filter = request.args.get('type', '')
    label_ids_filter = request.args.getlist('labels') # For multi-select

    # Base query for accepted builds
    builds_query = Build.query.join(Submission).filter(
        Submission.acceptance_state == AcceptanceState.ACCEPTED
    )

    # Apply filters
    if build_id_filter:
        builds_query = builds_query.filter(Build.id.ilike(f"%{build_id_filter}%"))
    if submission_id_filter:
        builds_query = builds_query.filter(Build.submission_id.ilike(f"%{submission_id_filter}%"))
    if submission_email_filter:
        builds_query = builds_query.filter(Submission.email.ilike(f"%{submission_email_filter}%"))
    if platform_filter:
        builds_query = builds_query.filter(Build.platform == platform_filter)
    if type_filter:
        builds_query = builds_query.filter(Build.type == type_filter)
    
    if label_ids_filter:
        if "none" in label_ids_filter:
            # User wants to see builds with no label, potentially along with others
            label_conditions = [Build.dataset_label_id == None]
            # Get actual integer IDs, filtering out "none"
            numeric_label_ids = [int(id) for id in label_ids_filter if id.isdigit()]
            if numeric_label_ids:
                label_conditions.append(Build.dataset_label_id.in_(numeric_label_ids))
            builds_query = builds_query.filter(or_(*label_conditions))
        else:
            # Only numeric IDs are selected
            numeric_label_ids = [int(id) for id in label_ids_filter if id.isdigit()]
            if numeric_label_ids:
                builds_query = builds_query.filter(Build.dataset_label_id.in_(numeric_label_ids))

    builds_pagination = builds_query.order_by(Build.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    all_labels = DatasetLabel.query.order_by(DatasetLabel.name).all()

    # Preserve filters in pagination links
    pagination_kwargs = {
        'build_id': build_id_filter,
        'submission_id': submission_id_filter,
        'submission_email': submission_email_filter,
        'platform': platform_filter,
        'type': type_filter,
        'labels': label_ids_filter
    }
    # Remove empty keys
    pagination_kwargs = {k: v for k, v in pagination_kwargs.items() if v}

    return render_template(
        'admin_dataset_manager.html',
        builds=builds_pagination.items,
        pagination=builds_pagination,
        labels=all_labels, # Pass all labels to template for dropdown
        title="Dataset Manager",
        active_page='dataset_manager',
        filters={
            'build_id': build_id_filter,
            'submission_id': submission_id_filter,
            'submission_email': submission_email_filter,
            'platform': platform_filter,
            'type': type_filter,
            'labels': label_ids_filter
        },
        pagination_kwargs=pagination_kwargs
    )

@app.route('/admin/api/builds/<build_id>/set-label', methods=['POST'])
def set_build_dataset_label(build_id):
    if not is_admin():
        return jsonify({'error': 'Unauthorized'}), 403

    build = Build.query.get_or_404(build_id)
    data = request.get_json()
    label_id = data.get('label_id')

    old_label_id = build.dataset_label_id
    new_label_id = label_id if label_id else None

    if old_label_id == new_label_id:
        return jsonify({'success': True, 'message': 'No change detected.'})

    old_label_name = DatasetLabel.query.get(old_label_id).name if old_label_id else "None"
    
    if new_label_id:
        label = DatasetLabel.query.get(new_label_id)
        if not label:
            return jsonify({'error': 'Invalid or inactive label'}), 400
        build.dataset_label_id = new_label_id
        new_label_name = label.name
    else:
        build.dataset_label_id = None
        new_label_name = "None"
    
    # Audit log
    audit_log = BuildAuditLog(
        build_id=build.id,
        admin_user_id=session['admin_user_id'],
        field_changed='dataset_label',
        old_value=old_label_name,
        new_value=new_label_name
    )
    db.session.add(audit_log)
    db.session.commit()
    return jsonify({'success': True, 'label_id': build.dataset_label_id})

@app.route('/admin/api/builds/<build_id>/update-details', methods=['POST'])
def update_build_details(build_id):
    if not is_admin():
        return jsonify({'error': 'Unauthorized'}), 403

    build = Build.query.get_or_404(build_id)
    data = request.get_json()
    field = data.get('field')
    value = data.get('value')

    if field not in ['platform', 'type']:
        return jsonify({'error': 'Invalid field specified'}), 400

    old_value = getattr(build, field)

    if old_value == value:
        return jsonify({'success': True, 'message': 'No change detected.'})

    setattr(build, field, value)

    # Audit log
    audit_log = BuildAuditLog(
        build_id=build.id,
        admin_user_id=session['admin_user_id'],
        field_changed=field,
        old_value=old_value,
        new_value=value
    )
    db.session.add(audit_log)
    db.session.commit()

    return jsonify({'success': True, f'{field}_updated': True})

@app.route('/admin/api/builds/<build_id>/audit-log')
def get_build_audit_log(build_id):
    if not is_admin():
        return jsonify({'error': 'Unauthorized'}), 403
    
    logs = BuildAuditLog.query.filter_by(build_id=build_id).order_by(BuildAuditLog.changed_at.desc()).all()
    
    result = [{
        'changed_at': log.changed_at.strftime('%Y-%m-%d %H:%M:%S UTC'),
        'admin_user': log.admin_user.username,
        'field_changed': log.field_changed.replace('_', ' ').title(),
        'old_value': log.old_value,
        'new_value': log.new_value
    } for log in logs]

    return jsonify(result)

# ────────────────────────────────────────────────────────────────────────────────
# Global response hardening
# ────────────────────────────────────────────────────────────────────────────────

# Add common security headers to all responses
@app.after_request
def set_security_headers(resp):
    # If the request is for the logviewer, its route handles its own headers.
    # We do nothing here to avoid overwriting them.
    if request.endpoint == 'public_email_log_view':
        return resp

    # For the main site (sister.sto-tools.org)
    resp.headers.setdefault('X-Frame-Options', 'DENY')

    csp = {
        'default-src': "'self'",
        'script-src': "'self' https://cdn.jsdelivr.net",
        'style-src': "'self' https://cdnjs.cloudflare.com",
        'font-src': "'self' https://cdnjs.cloudflare.com",
        'frame-src': "blob: https://logviewer.sto-tools.org",
        'child-src': "blob: https://logviewer.sto-tools.org",
        'object-src': "'none'",
        'base-uri': "'self'",
        'form-action': "'self'",
        'upgrade-insecure-requests': ""
    }
    csp_string = "; ".join([f"{key} {value}" for key, value in csp.items() if value is not None])
    resp.headers.setdefault('Content-Security-Policy', csp_string.strip())
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

# After app initialization
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(email=form.email.data)
        user.set_password(form.password.data)
        token = user.generate_verification_token()
        db.session.add(user)
        db.session.commit()
        send_verification_email(user.email, token)
        flash('A verification email has been sent to your email address.', 'info')
        return redirect(url_for('login'))
    return render_template('register.html', form=form, active_page='register')

@app.route('/verify_email/<token>')
def verify_email(token):
    user = User.query.filter_by(email_verification_token=token).first()
    if user:
        user.email_verified = True
        user.email_verification_token = None # Token should be single-use
        db.session.commit()
        flash('Your email has been verified! You can now log in.', 'success')
        return redirect(url_for('login'))
    else:
        flash('The verification link is invalid or has expired.', 'danger')
        return redirect(url_for('home'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = UserLoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            if user.email_verified:
                login_user(user)
                next_page = request.args.get('next')
                return redirect(next_page or url_for('home'))
            else:
                flash('Please verify your email address first.', 'warning')
        else:
            flash('Login Unsuccessful. Please check email and password', 'danger')
    return render_template('login.html', form=form, active_page='login')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.email_verified:
            token = user.generate_password_reset_token()
            db.session.commit()
            send_password_reset_email(user.email, token)
            flash('A password reset email has been sent to your email address.', 'info')
        else:
            # For security, we don't reveal if email exists or not
            flash('If the email exists and is verified, a password reset email has been sent.', 'info')
        return redirect(url_for('login'))
    return render_template('forgot_password.html', form=form, active_page='forgot_password')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    
    user = User.query.filter_by(password_reset_token=token).first()
    if not user or not user.is_password_reset_token_valid():
        flash('The password reset link is invalid or has expired.', 'danger')
        return redirect(url_for('forgot_password'))
    
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        user.clear_password_reset_token()
        db.session.commit()
        flash('Your password has been reset. You can now log in with your new password.', 'success')
        return redirect(url_for('login'))
    
    return render_template('reset_password.html', form=form, active_page='reset_password')

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def user_settings():
    form = UserSettingsForm()
    
    # Pre-populate the form with current user data
    if request.method == 'GET':
        form.contributor_recognition_enabled.data = current_user.contributor_recognition_enabled
        form.contributor_recognition_text.data = current_user.contributor_recognition_text
    
    if form.validate_on_submit():
        # Verify current password
        if not current_user.check_password(form.current_password.data):
            flash('Current password is incorrect.', 'danger')
            return render_template('user_settings.html', form=form, active_page='user_settings')
        
        # Update password if provided
        if form.new_password.data:
            current_user.set_password(form.new_password.data)
            flash('Password updated successfully.', 'success')
        
        # Update contributor recognition settings
        current_user.contributor_recognition_enabled = form.contributor_recognition_enabled.data
        current_user.contributor_recognition_text = form.contributor_recognition_text.data if form.contributor_recognition_enabled.data else None
        # Reset verification status if text changed
        if current_user.contributor_recognition_text != form.contributor_recognition_text.data:
            current_user.contributor_recognition_verified = False
        
        db.session.commit()
        flash('Settings updated successfully.', 'success')
        return redirect(url_for('user_settings'))
    
    return render_template('user_settings.html', form=form, active_page='user_settings')

@app.route('/me/submissions')
@login_required
def user_submissions():
    # The submissions property on the User model already fetches submissions
    # ordered by creation date, so we can use it directly.
    submissions = current_user.submissions
    return render_template('user_submissions.html', submissions=submissions, active_page='user_submissions')

@app.route('/api/me/submissions_data')
@login_required
def user_submissions_data():
    """
    Provides submission data for the logged-in user in a flat format
    matching the admin browser structure.
    """
    submissions = Submission.query.options(
        db.joinedload(Submission.builds).joinedload(Build.screenshots),
        db.joinedload(Submission.email_logs),
        db.joinedload(Submission.link_logs)
    ).filter_by(email=current_user.email).order_by(Submission.created_at.desc()).all()

    data_flat = []

    for sub in submissions:
        if not sub.builds:
            continue
        
        # Build the same 'events' structure as the admin browser
        events = []
        events.append({"type": "Submitted", "timestamp": sub.created_at.isoformat(), "method": "Web Form"})
        
        def find_log_for_event(timestamp, method):
            if method == 'link':
                return min(sub.link_logs, key=lambda log: abs(log.clicked_at - timestamp), default=None)
            elif method == 'email':
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
            log = find_log_for_event(sub.withdrawn_at, 'link')
            details = {}
            if log:
                details = {"log_id": log.id, "details": {"ip_address": log.ip_address, "user_agent": log.user_agent}}
            events.append({"type": "Withdrawn", "timestamp": sub.withdrawn_at.isoformat(), "method": "Link", **details})

        for log in sub.email_logs:
            is_decision_log = (sub.accepted_at and abs(log.received_at - sub.accepted_at) < timedelta(seconds=10))
            if not is_decision_log:
                 events.append({"type": "Email Received", "timestamp": log.received_at.isoformat(), "method": "Email", "log_id": log.id, "details": {"subject": log.subject, "from": log.from_address}})

        events.sort(key=lambda x: datetime.fromisoformat(x['timestamp'].replace('Z', '+00:00')))

        # Now, iterate over all builds within the submission and create flat screenshot data
        for build in sub.builds:
            platform = build.platform or "Unknown"
            sc_type = build.type or "Unknown"

            for sc in build.screenshots:
                screenshot_info = {
                    'id': sc.id,
                    'filename': sc.filename,
                    'build_id': str(build.id),
                    'submission_id': str(sub.id),
                    'submission_created': sub.created_at.isoformat(),
                    'is_accepted': sub.is_accepted,
                    'acceptance_state': sub.acceptance_state.value,
                    'is_withdrawn': sub.is_withdrawn,
                    'acceptance_token': sub.acceptance_token,
                    'email': sub.email,
                    'events': events,
                    'platform': platform,
                    'type': sc_type,
                    'date': sub.created_at.strftime('%Y-%m-%d')
                }
                data_flat.append(screenshot_info)
        
    return jsonify(data_flat)

@app.route('/api/me/email_log/<log_id>')
@login_required
def user_email_log(log_id):
    log = EmailLog.query.get_or_404(log_id)
    if log.submission.email != current_user.email:
        return jsonify({"error": "Unauthorized"}), 403
    
    return jsonify({
         "from": log.from_address,
         "to": log.to_address,
         "subject": log.subject,
         "body_html": log.body_html,
         "body_text": log.body_text,
         "received_at": log.received_at.isoformat()
    })

@app.route('/api/me/link_log/<log_id>')
@login_required
def user_link_log(log_id):
    log = LinkLog.query.get_or_404(log_id)
    if log.submission.email != current_user.email:
        return jsonify({"error": "Unauthorized"}), 403
    
    return jsonify({
        "ip_address": log.ip_address,
        "user_agent": log.user_agent,
        "clicked_at": log.clicked_at.isoformat()
    })

@app.route('/me/screenshot/<int:screenshot_id>')
@login_required
def user_screenshot_image(screenshot_id):
    sc = Screenshot.query.get_or_404(screenshot_id)
    # Security check: ensure the screenshot belongs to the current user.
    if sc.build.submission.email != current_user.email:
        return "Unauthorized", 403
        
    mime = 'image/png' if sc.filename.lower().endswith('png') else 'image/jpeg'
    return send_file(BytesIO(sc.data), mimetype=mime)

def make_user_thumbnail_cache_key(screenshot_id):
    """Generate a user-specific cache key for thumbnails."""
    return f"user_thumb_{current_user.email}_{screenshot_id}"

@app.route('/me/screenshot/<int:screenshot_id>/thumbnail')
@cache.cached(timeout=900, make_cache_key=make_user_thumbnail_cache_key)
@login_required
def user_screenshot_thumbnail(screenshot_id):
    sc = Screenshot.query.get_or_404(screenshot_id)
    # Security check: ensure the screenshot belongs to the current user.
    if sc.build.submission.email != current_user.email:
        return "Unauthorized", 403
    
    # Check if thumbnail_data field exists and has data
    if hasattr(sc, 'thumbnail_data') and sc.thumbnail_data:
        return send_file(BytesIO(sc.thumbnail_data), mimetype='image/jpeg')
    elif sc.data:
        # Generate thumbnail on-the-fly if not available
        thumbnail_data = generate_screenshot_thumbnail(sc.data)
        if thumbnail_data:
            return send_file(BytesIO(thumbnail_data), mimetype='image/jpeg')
        else:
            # Fallback to full image if thumbnail generation fails
            mime = 'image/png' if sc.filename.lower().endswith('png') else 'image/jpeg'
            return send_file(BytesIO(sc.data), mimetype=mime)
    else:
        return "No image data", 404

# --------------------- DIAGNOSTIC ROUTES ---------------------
@app.route('/test-flash')
def test_flash():
    flash('This is a test flash message.', 'info')
    return redirect(url_for('home'))

# ────────────────────────────────────────────────────────────────────────────────
# Email log viewer (served from logviewer.sto-tools.org)
# ────────────────────────────────────────────────────────────────────────────────
@app.route('/log/<log_id>')
def public_email_log_view(log_id):
    """Return raw email HTML/Text, validating access with a short-lived token."""
    token = request.args.get('token')
    if not token:
        return "Missing token", 401

    s = Serializer(current_app.config['SECRET_KEY'])
    try:
        # The token is valid for 60 seconds from its creation time.
        data = s.loads(token, max_age=60)
    except Exception: # Catches SignatureExpired, BadSignature, etc.
        return "Invalid or expired token", 403

    if str(data.get('log_id')) != str(log_id):
        return "Token is not valid for this resource", 403

    log = EmailLog.query.get_or_404(log_id)
    # The token validation is sufficient and replaces the previous session-based access control.

    body_html = log.body_html or ""
    body_text = log.body_text or "(no text body)"

    if not body_html:
        # Wrap plain text in <pre> for readability
        body_html = f"<pre>{body_text}</pre>"

    from flask import make_response
    resp = make_response(body_html)
    
    return resp

@app.route('/api/log-access-token/<log_id>')
def get_log_access_token(log_id):
    """Generate a short-lived token for viewing a specific email log."""
    log = EmailLog.query.get_or_404(log_id)

    # Verify that the current user has permission to view this log.
    # This check now correctly handles both admins and authenticated users without a decorator.
    if not (is_admin() or (current_user.is_authenticated and log.submission.email == current_user.email)):
        return jsonify({"error": "Unauthorized"}), 403

    s = Serializer(current_app.config['SECRET_KEY'])
    token = s.dumps({'log_id': str(log.id)})
    return jsonify({'token': token})

