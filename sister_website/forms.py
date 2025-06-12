from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, BooleanField, FileField
from wtforms.validators import DataRequired, Email, EqualTo, ValidationError

from .models import AdminUser


class UploadForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    agree_to_license = BooleanField(
        'I agree to license my submitted screenshots under the Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) license. '
        'This allows SISTER to use them for: (1) training machine learning recognition models, (2) future machine learning research, and (3) inclusion in the project\'s test suite. '
        'I acknowledge that this license is irrevocable for any data already distributed under these terms.',
        validators=[DataRequired(message="You must agree to the license terms to submit screenshots.")]
    )
    submit = SubmitField('Submit')


class LoginForm(FlaskForm):
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
