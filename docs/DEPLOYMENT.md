# Deploying SISTER Website on Apache2

This guide explains how to deploy the SISTER website using Apache2 on Ubuntu 24.04.1 LTS.

## Prerequisites

1. Ubuntu 24.04.1 LTS server
2. Root or sudo access
3. Domain name (optional)

## Installation Steps

### 1. Update System

```bash
sudo apt update
sudo apt upgrade -y
```

### 2. Install Required Packages

```bash
# Install Apache2 and Python tools
sudo apt install -y apache2 python3-pip python3-venv libapache2-mod-wsgi-py3

# Enable required Apache modules
sudo a2enmod wsgi
sudo a2enmod ssl  # If using HTTPS
```

### 3. Create Project Directory

```bash
# Create project directory
sudo mkdir -p /var/www/sister
sudo chown -R www-data:www-data /var/www/sister
```

### 4. Set Up Python Virtual Environment

```bash
# Create and activate virtual environment
cd /var/www/sister
python3 -m venv venv
source venv/bin/activate

# Install SISTER and dependencies
pip install sister-sto
pip install flask flask-sqlalchemy flask-wtf email-validator
```

### 5. Create WSGI File

Create `/var/www/sister/wsgi.py`:

```python
import sys
import os

# Add the site-packages of the virtual environment
activate_this = '/var/www/sister/venv/bin/activate_this.py'
with open(activate_this) as file_:
    exec(file_.read(), dict(__file__=activate_this))

# Add application directory to path
sys.path.insert(0, '/var/www/sister')

# Import app as application for WSGI
from sister_website import create_app
application = create_app()
```

### 6. Configure Apache Virtual Host

Create `/etc/apache2/sites-available/sister.conf`:

```apache
<VirtualHost *:80>
    ServerName sister.example.com  # Replace with your domain
    ServerAdmin webmaster@example.com

    DocumentRoot /var/www/sister

    WSGIDaemonProcess sister python-home=/var/www/sister/venv python-path=/var/www/sister user=www-data group=www-data threads=5
    WSGIProcessGroup sister
    WSGIScriptAlias / /var/www/sister/wsgi.py

    # Pass DOTENV_PATH to the application
    SetEnv DOTENV_PATH /var/www/.sister.env

    <Directory /var/www/sister>
        Require all granted
        AllowOverride All
    </Directory>

    ErrorLog ${APACHE_LOG_DIR}/sister_error.log
    CustomLog ${APACHE_LOG_DIR}/sister_access.log combined
</VirtualHost>
```

### 7. Set Up Application Directory

```bash
# Copy SISTER website files
cd /var/www/sister
git clone https://github.com/phillipod/SISTER.git .
mv sister_website/* .
rm -rf sister_website/

# Set permissions
sudo chown -R www-data:www-data /var/www/sister
sudo chmod -R 755 /var/www/sister
```

### 8. Create Instance Directory

```bash
mkdir -p /var/www/sister/instance
chown www-data:www-data /var/www/sister/instance
chmod 750 /var/www/sister/instance
```

### 9. Enable the Site

```bash
sudo a2dissite 000-default.conf  # Disable default site
sudo a2ensite sister.conf        # Enable SISTER site
sudo systemctl restart apache2
```

## SSL/HTTPS Configuration (Optional)

### 1. Install Certbot

```bash
sudo apt install -y certbot python3-certbot-apache
```

### 2. Obtain SSL Certificate

```bash
sudo certbot --apache -d sister.example.com
```

## File Permissions

Ensure correct permissions are set:

```bash
# Set ownership
sudo chown -R www-data:www-data /var/www/sister

# Set directory permissions
sudo find /var/www/sister -type d -exec chmod 755 {} \;

# Set file permissions
sudo find /var/www/sister -type f -exec chmod 644 {} \;

# Make scripts executable
sudo chmod +x /var/www/sister/wsgi.py
```

## Application Configuration

Create `/var/www/sister/instance/config.py`:

```python
# Flask application configuration
SECRET_KEY = 'your-secure-secret-key'  # Change this!
SQLALCHEMY_DATABASE_URI = 'sqlite:///sister.db'
UPLOAD_FOLDER = '/var/www/sister/uploads'
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

# SISTER configuration
SISTER_DATA_DIR = '/var/www/sister/data'
LOG_LEVEL = 'WARNING'
```

### MailerSend Configuration

SISTER uses MailerSend for sending transactional emails (e.g., consent forms for training data submissions). You'll need to configure MailerSend and update the application settings.

1.  **Create a MailerSend Account:**
    *   Sign up at [mailersend.com](https://www.mailersend.com/).

2.  **Verify Your Domain:**
    *   Follow MailerSend's instructions to add and verify your sending domain. This is crucial for email deliverability.

3.  **Get Your API Key:**
    *   Navigate to your domain settings in MailerSend and generate an API token. Note this token securely.

4.  **Configure Environment Variables:**
    *   The application uses a `.env` file for configuration, which should be placed outside the web root for security. The path to this file is specified by the `DOTENV_PATH` environment variable, which you'll set in the Apache configuration.

    Create the environment file at `/var/www/.sister.env`. The application will load this file based on the `DOTENV_PATH` environment variable set in the Apache configuration.

    Contents for `/var/www/.sister.env`:
    ```
    MAILERSEND_API_KEY='your_mailersend_api_key_here'
    MAILERSEND_FROM_EMAIL='your_verified_sender_email@yourdomain.com'
    MAILERSEND_REPLY_TO='your_reply_to_address@yourdomain.com' # Optional, defaults to FROM_EMAIL
    # Ensure SECRET_KEY is also set for token generation
    SECRET_KEY='your_strong_secret_key_for_flask_and_tokens'
    ```
    *   Replace placeholders with your actual MailerSend API key and verified email addresses.

5.  **Set Up Webhooks (for Email Replies):**
    *   To process user replies for license acceptance, you need to set up an inbound webhook in MailerSend.
    *   In MailerSend, go to "Inbound Routes" and create a new route.
    *   Configure the route to forward emails sent to a specific address (e.g., `replies@yourdomain.com`) to your application's webhook endpoint: `https://sister.example.com/api/webhooks/email-reply` (replace `sister.example.com` with your actual domain).
    *   MailerSend will provide a webhook signing secret. Add this to your `.env` file or `instance/config.py`:
    ```
    MAILERSEND_WEBHOOK_SECRET='your_mailersend_webhook_signing_secret'
    ```
    *   The `MAILERSEND_REPLY_TO` address in your `.env` file should ideally be the address you configure for the inbound route, or an address that MailerSend can process for replies if you are not using a dedicated inbound route for replies.

    **Note:** The application's `app.py` is set up to handle these environment variables. The `MAILERSEND_FROM_EMAIL` must be an email address associated with a verified domain in your MailerSend account.

## Directory Structure

After deployment, your directory structure should look like this:

```
/var/www/sister/
├── instance/
│   └── config.py
├── static/
│   ├── css/
│   ├── js/
│   └── img/
├── templates/
├── uploads/
├── venv/
├── wsgi.py
└── sister.py
```

## Testing the Deployment

1. Check Apache configuration:
```bash
sudo apache2ctl configtest
```

2. Check logs for errors:
```bash
sudo tail -f /var/log/apache2/sister_error.log
```

3. Test the website:
```bash
curl -I http://sister.example.com
```

## Troubleshooting

### Common Issues

1. **500 Internal Server Error**
   - Check Apache error logs
   - Verify permissions
   - Check Python dependencies

2. **Module not found errors**
   - Verify virtual environment activation
   - Check Python path in WSGI configuration

3. **Permission denied errors**
   - Check directory and file permissions
   - Verify www-data ownership

### Log Locations

- Apache error log: `/var/log/apache2/sister_error.log`
- Apache access log: `/var/log/apache2/sister_access.log`
- Application log: `/var/www/sister/log/sister.log`

## Maintenance

### Regular Tasks

1. Update system packages:
```bash
sudo apt update
sudo apt upgrade -y
```

2. Update Python packages:
```bash
source /var/www/sister/venv/bin/activate
pip install --upgrade sister-sto
```

3. Restart Apache:
```bash
sudo systemctl restart apache2
```

### Backup

Regularly backup these locations:
- `/var/www/sister/instance/`
- `/var/www/sister/uploads/`
- Application database 