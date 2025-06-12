from datetime import datetime
import uuid
from flask_sqlalchemy import SQLAlchemy

# SQLAlchemy database instance
# This is imported by the application and initialized there
# when create_app() is called.
db = SQLAlchemy()

class Submission(db.Model):
    __tablename__ = 'submission'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(120), nullable=False)
    acceptance_token = db.Column(db.String(64), unique=True, nullable=False)
    is_accepted = db.Column(db.Boolean, default=False)
    accepted_at = db.Column(db.DateTime, nullable=True)
    acceptance_method = db.Column(db.String(10), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    builds = db.relationship('Build', backref='submission', lazy=True)
    email_logs = db.relationship('EmailLog', backref='submission', lazy=True, order_by='EmailLog.received_at')
    link_logs = db.relationship('LinkLog', backref='submission', lazy=True, order_by='LinkLog.clicked_at')

class Build(db.Model):
    __tablename__ = 'build'
    id = db.Column(db.String(36), primary_key=True)
    submission_id = db.Column(db.String(36), db.ForeignKey('submission.id'), nullable=False)
    platform = db.Column(db.String(10), nullable=False)
    type = db.Column(db.String(10), nullable=False)
    is_accepted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    accepted_at = db.Column(db.DateTime, nullable=True)
    acceptance_method = db.Column(db.String(10), nullable=True)
    screenshots = db.relationship('Screenshot', backref='build', lazy=True)

class Screenshot(db.Model):
    __tablename__ = 'screenshot'
    id = db.Column(db.Integer, primary_key=True)
    build_id = db.Column(db.String(36), db.ForeignKey('build.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    md5sum = db.Column(db.String(32), nullable=False, index=True)
    data = db.Column(db.LargeBinary, nullable=True)
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
