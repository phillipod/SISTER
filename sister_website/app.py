import os
import hmac
import hashlib
import json
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
import uuid  # Ensure uuid is imported for new models
import magic
import re
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import logging  # Keep this one for current_app.logger
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
)
from .forms import UploadForm, LoginForm, AdminUserForm, ChangePasswordForm
from .email_utils import (
    send_consent_email,
    send_reply_confirmation_email,
    verify_webhook_signature,
)
# import magic # Removed, will use the one below with other Flask imports

# Initialize extensions
cache = Cache()


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

    # Print all relevant environment variables for debugging
    app.logger.info("Environment variables:")
    for var in ['UPLOAD_FOLDER', 'DATABASE_URL', 'DOTENV_PATH']:
        app.logger.info(f"{var} = {os.getenv(var)}")

    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key-please-change')

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
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
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



def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_mime(file_storage):
    """Checks if the file's MIME type is allowed."""
    mime_type = None
    is_allowed = False
    try:
        sample = file_storage.read(2048)  # Read a chunk for MIME detection
        mime_type = magic.from_buffer(sample, mime=True)
        current_app.logger.info(
            "Detected MIME type: %s for file: %s", mime_type, file_storage.filename
        )
        is_allowed = mime_type in ALLOWED_MIME_TYPES
        current_app.logger.info(
            "MIME type %s is_allowed: %s", mime_type, is_allowed
        )
    except ImportError as ie:
        current_app.logger.error(
            "ImportError in allowed_mime: %s", ie, exc_info=True
        )
        # Fallback: If python-magic is not available, you might choose to skip MIME check or deny all.
        # For security, denying is safer if MIME check is critical.
        is_allowed = False  # Or True if you want to allow uploads if magic fails
    except Exception as e:
        current_app.logger.error(
            "Exception in allowed_mime for %s: %s", file_storage.filename, e,
            exc_info=True,
        )
        is_allowed = False  # Default to not allowed if there's an error in checking
    finally:
        file_storage.seek(0)  # IMPORTANT: Reset stream for subsequent reads
    return is_allowed

def is_admin():
    """Return True if the current session belongs to a logged in admin."""
    return session.get('admin_user_id') is not None

def save_screenshot(file):
    """Saves a screenshot file, calculates its MD5, and creates a Screenshot record in memory without saving to disk."""
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

    # Proceed with processing if both checks passed
    if is_file_allowed and is_mime_allowed:
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
    # This part is reached if the initial checks (is_file_allowed and is_mime_allowed) failed earlier
    current_app.logger.warning(f"save_screenshot: Returning None for {filename_for_log} due to failed pre-checks (extension or MIME).")
    return None

def generate_acceptance_token(submission_id, email):
    """Generate a secure token for email acceptance for a Submission"""
    secret = os.getenv('SECRET_KEY', 'dev-key-please-change')
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
            for file_in_request in actual_screenshots_files:
                screenshot = save_screenshot(file_in_request) 
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
        current_app.logger.info(f"Logged link acceptance for submission {submission.id} from IP {request.remote_addr}")
    except Exception as e_link_log:
        # Log error but don't fail the acceptance if link logging fails
        current_app.logger.error(f"Failed to create LinkLog for submission {submission.id}: {e_link_log}", exc_info=True)

    # Mark all associated Builds as accepted
    for build_item in submission.builds:
        build_item.is_accepted = True
        build_item.accepted_at = submission.accepted_at # Use submission's acceptance time
        build_item.acceptance_method = 'link'
    
    try:
        db.session.commit()
        success_message = "Thank you for accepting the license for your submission!"
        if request.method == 'GET':
            # Clear any existing messages before setting the success message
            session.pop('_flashes', None)
            flash(success_message, 'success')
            return render_template('acceptance_thank_you.html', submission=submission)
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
    # Get all submissions with their builds and screenshots
    submissions = Submission.query.options(
        db.joinedload(Submission.builds).joinedload(Build.screenshots)
    ).all()
    
    # Initialize stats
    stats = {
        'total_submissions': 0,
        'total_accepted': 0,
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
        if submission.is_accepted:
            stats['total_accepted'] += 1
        
        for build in submission.builds:
            # Ensure platform and type are valid keys
            platform_key = build.platform if build.platform in stats['by_platform_type'] else None
            type_key = build.type if platform_key and build.type in stats['by_platform_type'][platform_key] else None

            if platform_key and type_key:
                stats['by_platform_type'][platform_key][type_key]['total_builds'] += 1
                if submission.is_accepted:
                    stats['by_platform_type'][platform_key][type_key]['accepted_builds'] += 1

            for screenshot in build.screenshots:
                stats['total_screenshots'] += 1
                # Stats for screenshot types (labels), derived from build
                # Ensure build relationship is loaded. The query in training_data_stats should handle this.
                # Submission.query.options(db.joinedload(Submission.builds).joinedload(Build.screenshots))
                if screenshot.build and screenshot.build.type in stats['by_screenshot_type']:
                    stats['by_screenshot_type'][screenshot.build.type]['total'] += 1
                    if submission.is_accepted:
                        stats['by_screenshot_type'][screenshot.build.type]['accepted'] += 1
                
                # Aggregate screenshot counts within platform/type as well
                if platform_key and type_key:
                    stats['by_platform_type'][platform_key][type_key]['total_screenshots'] += 1
                    if submission.is_accepted:
                        stats['by_platform_type'][platform_key][type_key]['accepted_screenshots'] += 1
    
    # Ensure by_type is a standard dict for the template, which it already is now
    # No conversion needed if initialized as a dict with predefined keys
    
    return render_template('training_data_stats.html', 
                         stats=stats, 
                         now=datetime.utcnow(),
                         active_page='training_data_stats')

@app.route('/acceptance-thank-you')
def acceptance_thank_you():
    return render_template('pages/acceptance_thank_you.html', active_page='acceptance_thank_you')


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    form = LoginForm()
    if form.validate_on_submit():
        user = AdminUser.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            if user.is_locked:
                flash('This account is locked.', 'danger')
                return redirect(url_for('admin_login'))
            session['admin_user_id'] = user.id
            flash('Logged in as admin.', 'success')
            next_page = request.args.get('next') or url_for('browse_screenshots')
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
        return redirect(url_for('admin_login'))
    user_to_delete = AdminUser.query.get_or_404(user_id)
    if user_to_delete.id == session['admin_user_id']:
        flash("You cannot delete your own account.", 'danger')
    else:
        db.session.delete(user_to_delete)
        db.session.commit()
        flash(f"User {user_to_delete.username} has been deleted.", 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/screenshots')
def browse_screenshots():
    if not is_admin():
        return redirect(url_for('admin_login', next=request.path))
    return render_template('admin_screenshots.html', active_page='admin_screenshots')


@app.route('/admin/api/screenshots')
def admin_screenshots_data():
    if not is_admin():
        return jsonify({'error': 'unauthorized'}), 403
    
    # Eagerly load related data to prevent N+1 query problems
    screenshots = Screenshot.query.options(
        db.joinedload(Screenshot.build).joinedload(Build.submission)
    ).all()

    tree = {}
    for sc in screenshots:
        # Get data from related models
        build = sc.build
        submission = build.submission
        
        # Structure the data
        plat = build.platform
        typ = build.type
        date_key = submission.created_at.strftime('%Y-%m-%d')

        # Create nested dictionaries if they don't exist
        tree.setdefault(plat, {}).setdefault(typ, {}).setdefault(date_key, []).append({
            'id': sc.id,
            'filename': sc.filename,
            'is_accepted': submission.is_accepted,
            'submission_id': submission.id,
            'email': submission.email,
        })
    return jsonify(tree)


@app.route('/admin/api/screenshot_info/<int:screenshot_id>')
def admin_screenshot_info(screenshot_id):
    if not is_admin():
        return jsonify({'error': 'unauthorized'}), 403
    sc = Screenshot.query.get_or_404(screenshot_id)
    info = {
        'id': sc.id,
        'filename': sc.filename,
        'is_accepted': sc.build.submission.is_accepted,
    }
    return jsonify(info)


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
    if not verify_webhook_signature(request_data, signature_header, webhook_secret):
        current_app.logger.warning("Email webhook: Invalid webhook signature")
        return jsonify({"status": "error", "message": "Invalid signature"}), 401

    try:
        # Parse JSON data (already verified the signature)
        data = request.get_data()
        if not data:
            current_app.logger.warning("Email webhook: No JSON data received.")
            return jsonify({"status": "error", "message": "No JSON data received"}), 400
        
        #logger.info(f"Email webhook: Received data: {json.dumps(data, indent=2)}")

        # --- START: Debugging Email Parsing --- 
        current_app.logger.info(f"Email webhook: Debug - Raw 'from' field: {data.get('from')}")
        current_app.logger.info(f"Email webhook: Debug - Raw 'to' field: {data.get('to')}")
        current_app.logger.info(f"Email webhook: Debug - Raw 'envelopeRecipients' field: {data.get('envelopeRecipients')}")
        # --- END: Debugging Email Parsing ---

        # --- START: Enhanced Header and Email Info Extraction ---
        all_headers_raw = data.get('headers', []) 
        headers_json_str = json.dumps(all_headers_raw) if all_headers_raw else None
        
        headers_dict = {}
        if isinstance(all_headers_raw, list):
            headers_dict = {h.get('key', '').lower(): h.get('value', '') for h in all_headers_raw if isinstance(h, dict) and h.get('key')}
        elif isinstance(all_headers_raw, dict): 
            headers_dict = {k.lower(): v for k, v in all_headers_raw.items()}

        message_id_value = headers_dict.get('message-id')

        from_field_data = data.get('from') # Get the 'from' object, could be dict or None
        from_email_address = None
        if isinstance(from_field_data, dict):
            from_value_list = from_field_data.get('value')
            if isinstance(from_value_list, list) and from_value_list:
                sender_obj = from_value_list[0]
                if isinstance(sender_obj, dict):
                    from_email_address = sender_obj.get('address', '').lower() or sender_obj.get('email', '').lower()
        if not from_email_address:
            current_app.logger.warning(f"Email webhook: Could not parse 'from_email_address' from 'from' field: {from_field_data}")

        to_email_address = None
        envelope_recipients = data.get('envelopeRecipients', []) 
        if isinstance(envelope_recipients, list) and envelope_recipients:
            if isinstance(envelope_recipients[0], str):
                to_email_address = envelope_recipients[0].lower()
        
        if not to_email_address: # Fallback if envelopeRecipients was not present or empty
            to_field_data = data.get('to') # Get the 'to' object, could be dict or None
            if isinstance(to_field_data, dict):
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

        reply_lower = reply_only_text.lower()
        is_acceptance_in_reply = any(keyword in reply_lower for keyword in acceptance_keywords)
        is_disagreement_in_reply = any(keyword in reply_lower for keyword in disagreement_keywords)

        current_app.logger.info(f"Email webhook: Decision check for submission_id='{submission_id}': acceptance_found='{is_acceptance_in_reply}', disagreement_found='{is_disagreement_in_reply}'")
        
        decision_for_email = "Reply Received - No explicit decision keywords detected" # Default
        action_taken = False

        if is_disagreement_in_reply:
            current_app.logger.info(f"Email webhook: Disagreement keywords found for submission_id='{submission_id}'. Submission will NOT be accepted based on this reply.")
            decision_for_email = "License Agreement Declined (based on your reply)"
            # No changes to submission.is_accepted or build.is_accepted needed here, they remain False or as they were.
            # Log the email, as it's a significant interaction
            try:
                submission_for_log = Submission.query.get(submission_id)
                if submission_for_log:
                    email_html_content = data.get('html', '')
                    new_email_log = EmailLog(
                        submission_id=submission_for_log.id,
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
                    current_app.logger.info(f"Email webhook: Email log created for disagreement reply for submission_id='{submission_for_log.id}', EmailLog ID {new_email_log.id}.")
                else:
                    current_app.logger.warning(f"Email webhook: Submission '{submission_id}' not found when trying to log disagreement email.")
            except Exception as e_log_disagree:
                db.session.rollback()
                current_app.logger.error(f"Email webhook: Failed to log disagreement email for submission_id='{submission_id}': {e_log_disagree}", exc_info=True)
            
            email_sent_successfully = send_reply_confirmation_email(from_email_address, submission_id, decision_for_email, to_email_address)
            response_message = f"Disagreement processed for submission {submission_id}. License not accepted."
            if email_sent_successfully:
                response_message += " Confirmation email sent."
            else:
                response_message += " Confirmation email FAILED to send (check logs)."
            return jsonify({"status": "info", "message": response_message}), 200

        elif is_acceptance_in_reply: # Only if not disagreement
            submission = Submission.query.get(submission_id)
            
            if not submission:
                current_app.logger.warning(f"Email webhook: Submission with ID '{submission_id}' not found.")
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
                current_app.logger.info(f"Email webhook: Email log created for submission_id='{submission.id}', message_id='{message_id_value}' to EmailLog ID {new_email_log.id}.")
            except Exception as e_log:
                db.session.rollback()
                current_app.logger.error(f"Email webhook: Failed to log email for submission_id='{submission.id}': {e_log}", exc_info=True)
                # Continue processing acceptance even if logging failed for now.

            if submission.is_accepted:
                current_app.logger.info(f"Email webhook: Submission '{submission_id}' already accepted on {submission.accepted_at} by {submission.acceptance_method}.")
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
                current_app.logger.info(f"Email webhook: Successfully accepted Submission '{submission_id}' and its builds via email reply.")
                decision_for_email = "License Agreement Accepted"
                email_sent_successfully = send_reply_confirmation_email(from_email_address, submission_id, decision_for_email, to_email_address)
                response_message = f"Submission {submission_id} accepted via email."
                if email_sent_successfully:
                    response_message += " Acceptance confirmation email sent."
                else:
                    response_message += " Acceptance confirmation email FAILED to send (check logs)."
                return jsonify({"status": "success", "message": response_message}), 200
            except Exception as e_commit:
                db.session.rollback()
                current_app.logger.error(f"Email webhook: Database error committing acceptance for submission_id '{submission_id}': {e_commit}", exc_info=True)
                # Optionally, send a confirmation of failure if appropriate, but be cautious about error loops.
                # For now, we don't send an email on DB commit failure to avoid potential loops if email sending also fails.
                return jsonify({"status": "error", "message": "Database error during acceptance."}), 500
        else:
            current_app.logger.info(f"Email webhook: No acceptance or disagreement keywords found in email body for submission_id='{submission_id}'. No action taken on submission status.")
            # decision_for_email is already defaulted to "Reply Received - No explicit decision keywords detected"
            email_sent_successfully = send_reply_confirmation_email(from_email_address, submission_id, decision_for_email, to_email_address)
            response_message = "No decision keywords found. Reply logged."
            if email_sent_successfully:
                response_message += " Neutral confirmation email sent."
            else:
                response_message += " Neutral confirmation email FAILED to send (check logs)."
            return jsonify({"status": "info" if email_sent_successfully else "warning", "message": response_message}), 200

    except Exception as e:
        current_app.logger.error(f"Email webhook: General error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "An internal error occurred."}), 500

@app.route('/admin/api/resend-consent/<submission_id>', methods=['POST'])
def resend_consent_email(submission_id):
    if not is_admin():
        return jsonify({'error': 'unauthorized'}), 403
    
    submission = Submission.query.get_or_404(submission_id)
    
    if submission.is_accepted:
        return jsonify({'error': 'Submission already accepted'}), 400
    
    # Generate a new acceptance token
    submission.acceptance_token = generate_acceptance_token(submission.id, submission.email)
    
    # Prepare consents for email
    consents_for_email = {
        'agreed_to_license': True  # Since they're resending, we assume they agreed
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
