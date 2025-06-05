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
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    consent_ml_recognition = db.Column(db.Boolean, default=False)
    consent_ml_future = db.Column(db.Boolean, default=False)
    consent_test_suite = db.Column(db.Boolean, default=False)
    consent_confirmed = db.Column(db.Boolean, default=False)
    consent_confirmed_at = db.Column(db.DateTime)
    screenshots = db.relationship('Screenshot', backref='build', lazy=True)

class Screenshot(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    build_id = db.Column(db.String(36), db.ForeignKey('build.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    screenshot_type = db.Column(db.String(50), nullable=False)  # 'space' or 'ground'
    uploaded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class UploadForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    consent_ml_recognition = BooleanField('I understand my screenshots will be published in the ML training data repository on GitHub and used for ML training - label recognition')
    consent_ml_future = BooleanField('I understand my screenshots will be published in the ML training data repository on GitHub and may be used for future ML training (limited to label recognition, build classification, icon group detection, or icon recognition)')
    consent_test_suite = BooleanField('I understand my screenshots will be published in the core repository on GitHub and used in the core test suite')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_screenshot(file, build_id, screenshot_type):
    if file and allowed_file(file.filename):
        screenshot_id = str(uuid.uuid4())
        original_filename = secure_filename(file.filename)
        filename = f"{screenshot_id}_{original_filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        screenshot = Screenshot(
            id=screenshot_id,
            build_id=build_id,
            filename=filename,
            original_filename=original_filename,
            screenshot_type=screenshot_type
        )
        return screenshot
    return None

def send_consent_email(email, builds, consents):
    message = Mail(
        from_email=os.getenv('FROM_EMAIL', 'noreply@example.com'),
        to_emails=email,
        subject='STO Build Screenshots Submission - Consent Form',
        html_content=render_template('email_template.html',
                                  builds=builds,
                                  consents=consents)
    )
    try:
        sg = SendGridAPIClient(os.getenv('SENDGRID_API_KEY'))
        response = sg.send(message)
        return response.status_code == 202
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

@app.route('/', methods=['GET', 'POST'])
def upload_build():
    form = UploadForm()
    if form.validate_on_submit():
        builds = []
        build_index = 0
        has_screenshots = False
        
        while True:
            space_files = request.files.getlist(f'space_screenshots_{build_index}')
            ground_files = request.files.getlist(f'ground_screenshots_{build_index}')
            
            if not any(f.filename for f in space_files + ground_files):
                break
                
            build_id = str(uuid.uuid4())
            build = Build(
                id=build_id,
                email=form.email.data,
                consent_ml_recognition=form.consent_ml_recognition.data,
                consent_ml_future=form.consent_ml_future.data,
                consent_test_suite=form.consent_test_suite.data
            )
            
            screenshots = []
            
            # Process space screenshots
            for file in space_files:
                if file.filename:
                    screenshot = save_screenshot(file, build_id, 'space')
                    if screenshot:
                        screenshots.append(screenshot)
                        has_screenshots = True
            
            # Process ground screenshots
            for file in ground_files:
                if file.filename:
                    screenshot = save_screenshot(file, build_id, 'ground')
                    if screenshot:
                        screenshots.append(screenshot)
                        has_screenshots = True
            
            if screenshots:
                build.screenshots = screenshots
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
        
        return redirect(url_for('upload_build'))
    
    return render_template('index.html', form=form)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.run(debug=True) 