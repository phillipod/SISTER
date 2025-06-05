import os
from datetime import datetime
from flask import Flask, render_template, request, flash, redirect, url_for, session
from werkzeug.utils import secure_filename
from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField
from wtforms.validators import DataRequired, Email
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
import uuid

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key-please-change')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB max file size
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///submissions.db'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

db = SQLAlchemy(app)

class Build(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    email = db.Column(db.String(120), nullable=False)
    consent_ml_recognition = db.Column(db.Boolean, default=False)
    consent_ml_future = db.Column(db.Boolean, default=False)
    consent_test_suite = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    screenshots = db.relationship('Screenshot', backref='build', lazy=True)

class Screenshot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    build_id = db.Column(db.String(36), db.ForeignKey('build.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # 'space' or 'ground'
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_test_suite = db.Column(db.Boolean, default=False)  # New field to track test suite allocation

class UploadForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    consent_ml_recognition = BooleanField('I consent to my screenshots being used for machine learning recognition training')
    consent_ml_future = BooleanField('I consent to my screenshots being used for future machine learning research')
    consent_test_suite = BooleanField('I consent to my screenshots being used in the test suite')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_screenshot(file, build_id, build_type, is_test_suite=False):
    if file and allowed_file(file.filename):
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

def send_consent_email(email, builds, consents):
    try:
        sg = SendGridAPIClient(os.getenv('SENDGRID_API_KEY'))
        
        message = Mail(
            from_email=os.getenv('SENDGRID_FROM_EMAIL'),
            to_emails=email,
            subject='SISTER - Build Screenshot Submission Confirmation',
            html_content=render_template(
                'email_template.html',
                builds=builds,
                consents=consents,
                timestamp=datetime.utcnow()
            )
        )
        
        response = sg.send(message)
        return response.status_code == 202
    except Exception as e:
        print(f"SendGrid error: {e}")
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
            build = Build(
                id=build_id,
                email=form.email.data,
                consent_ml_recognition=form.consent_ml_recognition.data,
                consent_ml_future=form.consent_ml_future.data,
                consent_test_suite=form.consent_test_suite.data
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
            
            consents = {
                'ml_recognition': form.consent_ml_recognition.data,
                'ml_future': form.consent_ml_future.data,
                'test_suite': form.consent_test_suite.data
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

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.run(debug=True) 