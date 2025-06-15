from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, BooleanField, FileField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, ValidationError

from .models import AdminUser, DatasetLabel, User


class UploadForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    agree_to_license = BooleanField(
        'I agree to license my submitted screenshots under the Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) license. '
        'This allows SISTER to use them for: (1) training machine learning recognition models, (2) future machine learning research, and (3) inclusion in the project\'s test suite. '
        'I acknowledge that this license is irrevocable for any data already distributed under these terms.',
        validators=[DataRequired(message="You must agree to the license terms to submit screenshots.")]
    )
    submit = SubmitField('Submit')


class RegistrationForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[
        DataRequired(),
        EqualTo('confirm_password', message='Passwords must match.')
    ])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired()])
    submit = SubmitField('Register')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('That email is already taken. Please use a different one.')


class UserLoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')


class AdminLoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')


class ChangePasswordForm(FlaskForm):
    password = PasswordField('New Password', validators=[
        DataRequired(),
        EqualTo('confirm_password', message='Passwords must match.')
    ])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired()])
    submit = SubmitField('Change Password')


class AdminUserForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[
        DataRequired(),
        EqualTo('confirm_password', message='Passwords must match.')
    ])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired()])
    submit = SubmitField('Create User')

    def validate_username(self, username):
        user = AdminUser.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('That username is already taken. Please choose a different one.')


class DatasetLabelForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])
    description = TextAreaField('Description')
    submit = SubmitField('Save Label')

    def validate_name(self, name):
        # On edit, this check is slightly different, handled in the route
        label = DatasetLabel.query.filter_by(name=name.data).first()
        if label:
            raise ValidationError('A label with this name already exists.')


class ForgotPasswordForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Send Reset Link')


class ResetPasswordForm(FlaskForm):
    password = PasswordField('New Password', validators=[
        DataRequired(),
        EqualTo('confirm_password', message='Passwords must match.')
    ])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired()])
    submit = SubmitField('Reset Password')


class UserSettingsForm(FlaskForm):
    current_password = PasswordField('Current Password', validators=[DataRequired()])
    new_password = PasswordField('New Password', validators=[
        EqualTo('confirm_password', message='Passwords must match.')
    ])
    confirm_password = PasswordField('Confirm New Password')
    contributor_recognition_enabled = BooleanField('Participate in contributor recognition program')
    contributor_recognition_text = TextAreaField(
        'How would you like to be acknowledged? (optional)',
        render_kw={'placeholder': 'e.g., Your Name, Your Name (username), Anonymous, etc.'}
    )
    submit = SubmitField('Save Settings')

    def validate_new_password(self, new_password):
        if new_password.data and not self.confirm_password.data:
            raise ValidationError('Please confirm your new password.')
        if not new_password.data and self.confirm_password.data:
            raise ValidationError('Please enter a new password.')
