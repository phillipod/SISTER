from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField, PasswordField
from wtforms.validators import DataRequired, Email

class UploadForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    agree_to_license = BooleanField(
        'I agree to license my submitted screenshots under the Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) license. '
        'This allows SISTER to use them for: (1) training machine learning recognition models, (2) future machine learning research, and (3) inclusion in the project\'s test suite. '
        'I acknowledge that this license is irrevocable for any data already distributed under these terms.',
        validators=[DataRequired(message="You must agree to the license terms to submit screenshots.")]
    )


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
