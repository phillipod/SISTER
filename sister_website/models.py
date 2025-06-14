from datetime import datetime
import uuid
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.mysql import LONGBLOB
from werkzeug.security import generate_password_hash, check_password_hash
import enum
import secrets
from flask_login import UserMixin

# SQLAlchemy database instance
# This is imported by the application and initialized there
# when create_app() is called.
db = SQLAlchemy()

class AcceptanceState(enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"

class Submission(db.Model):
    __tablename__ = 'submission'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(120), nullable=False)
    acceptance_token = db.Column(db.String(64), unique=True, nullable=False)
    acceptance_state = db.Column(db.Enum(AcceptanceState), default=AcceptanceState.PENDING, nullable=False)
    accepted_at = db.Column(db.DateTime, nullable=True)
    acceptance_method = db.Column(db.String(10), nullable=True)
    is_withdrawn = db.Column(db.Boolean, default=False, nullable=False)
    withdrawn_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    builds = db.relationship('Build', backref='submission', lazy=True)
    email_logs = db.relationship('EmailLog', backref='submission', lazy=True, order_by='EmailLog.received_at')
    link_logs = db.relationship('LinkLog', backref='submission', lazy=True, order_by='LinkLog.clicked_at')

    @property
    def is_accepted(self):
        """Property for backward compatibility and semantic clarity."""
        return self.acceptance_state == AcceptanceState.ACCEPTED

class Build(db.Model):
    __tablename__ = 'build'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    submission_id = db.Column(db.String(36), db.ForeignKey('submission.id'), nullable=False)
    platform = db.Column(db.String(10), nullable=False)
    type = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    screenshots = db.relationship('Screenshot', backref='build', lazy=True)
    dataset_label_id = db.Column(db.Integer, db.ForeignKey('dataset_label.id'), nullable=True)

    @property
    def is_accepted(self):
        """For compatibility, check the submission's status."""
        return self.submission.is_accepted
    
    @property
    def acceptance_state(self):
        """Convenience property to access the submission's acceptance state."""
        return self.submission.acceptance_state

class Screenshot(db.Model):
    __tablename__ = 'screenshot'
    id = db.Column(db.Integer, primary_key=True)
    build_id = db.Column(db.String(36), db.ForeignKey('build.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    md5sum = db.Column(db.String(32), nullable=False, index=True)
    data = db.Column(LONGBLOB, nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

class EmailLog(db.Model):
    __tablename__ = 'email_log'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    submission_id = db.Column(db.String(36), db.ForeignKey('submission.id'), nullable=False)
    message_id_header = db.Column(db.String(512), nullable=True, index=True)
    from_address = db.Column(db.String(255), nullable=True)
    to_address = db.Column(db.String(255), nullable=True)
    subject = db.Column(db.String(512), nullable=True)
    body_text = db.Column(db.Text, nullable=True)
    body_html = db.Column(db.Text, nullable=True)
    headers_json = db.Column(db.Text, nullable=True)
    received_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<EmailLog {self.id} for Submission {self.submission_id}>'

class LinkLog(db.Model):
    __tablename__ = 'link_log'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    submission_id = db.Column(db.String(36), db.ForeignKey('submission.id'), nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)
    clicked_at = db.Column(db.DateTime, default=datetime.utcnow)
    token_used = db.Column(db.String(64), nullable=False)

    def __repr__(self):
        return f'<LinkLog {self.id} for Submission {self.submission_id} from {self.ip_address}>'


class User(db.Model, UserMixin):
    __tablename__ = 'user'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    email_verification_token = db.Column(db.String(64), unique=True, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_verification_token(self):
        token = secrets.token_urlsafe(32)
        self.email_verification_token = token
        return token

    @property
    def submissions(self):
        return Submission.query.filter_by(email=self.email).order_by(Submission.created_at.desc()).all()

class AdminUser(db.Model):
    __tablename__ = 'admin_user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_locked = db.Column(db.Boolean, default=False, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class DatasetLabel(db.Model):
    __tablename__ = 'dataset_label'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    builds = db.relationship('Build', backref='dataset_label', lazy=True)

    def __repr__(self):
        return f'<DatasetLabel {self.name}>'

class BuildAuditLog(db.Model):
    __tablename__ = 'build_audit_log'
    id = db.Column(db.Integer, primary_key=True)
    build_id = db.Column(db.String(36), db.ForeignKey('build.id'), nullable=False)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_user.id'), nullable=False)
    changed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    field_changed = db.Column(db.String(50), nullable=False)
    old_value = db.Column(db.String(255), nullable=True)
    new_value = db.Column(db.String(255), nullable=True)

    admin_user = db.relationship('AdminUser', backref=db.backref('audit_logs', lazy=True))
    build = db.relationship('Build', backref=db.backref('audit_logs', lazy=True))

    def __repr__(self):
        return f'<BuildAuditLog {self.id} - Build {self.build_id}>'
