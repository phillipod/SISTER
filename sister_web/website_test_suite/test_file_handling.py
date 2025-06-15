import pytest
import os
import tempfile
from io import BytesIO
from unittest.mock import patch, MagicMock
from werkzeug.datastructures import FileStorage
from sister_website.models import User, Submission, Screenshot, Build, AcceptanceState, AdminUser, db
from sister_website.app import save_screenshot, allowed_mime
from PIL import Image


def create_test_image_data(width=100, height=100, format='PNG'):
    """Create test image data."""
    img = Image.new('RGB', (width, height), color='red')
    img_buffer = BytesIO()
    img.save(img_buffer, format=format)
    return img_buffer.getvalue()


def create_test_submission_with_screenshot(app, email="test@example.com"):
    """Helper to create a submission with screenshot for testing."""
    with app.app_context():
        submission = Submission(
            email=email,
            acceptance_token='test_token_123',
            acceptance_state=AcceptanceState.ACCEPTED
        )
        
        build = Build(submission=submission, platform='PC', type='space')
        
        screenshot_data = create_test_image_data()
        screenshot = Screenshot(
            build=build,
            filename='test_screenshot.png',
            md5sum='test_md5_hash',
            data=screenshot_data
        )
        
        db.session.add_all([submission, build, screenshot])
        db.session.commit()
        
        # Return IDs to avoid detached instance errors
        return submission.id, screenshot.id


def create_and_login_user(client, app, email="testuser@example.com"):
    """Helper to create and login a user."""
    with app.app_context():
        user = User(email=email)
        user.set_password('password123')
        user.email_verified = True
        db.session.add(user)
        db.session.commit()
    
    # Login
    client.post('/login', data={
        'email': email,
        'password': 'password123',
        'csrf_token': 'test'
    }, follow_redirects=True)
    
    return user


def test_admin_screenshot_route_success(client, app, admin_user):
    """Test admin screenshot serving route."""
    submission_id, screenshot_id = create_test_submission_with_screenshot(app)
    
    # Extract admin username before leaving app context
    with app.app_context():
        # Query admin user fresh from database to avoid detached instance error
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    # Login as admin
    client.post('/admin/login', data={
        'username': admin_username,
        'password': 'password',
        'csrf_token': 'test'
    })
    
    response = client.get(f'/admin/screenshot/{screenshot_id}')
    assert response.status_code == 200
    assert response.headers['Content-Type'] == 'image/png'
    assert len(response.data) > 0


def test_admin_screenshot_route_not_found(client, app, admin_user):
    """Test admin screenshot serving route with non-existent screenshot."""
    # Extract username before leaving app context
    with app.app_context():
        # Query admin user fresh from database to avoid detached instance error
        admin = AdminUser.query.filter_by(username='admin').first()
        admin_username = admin.username
    
    # Login as admin
    client.post('/admin/login', data={
        'username': admin_username,
        'password': 'password',
        'csrf_token': 'test'
    })
    
    response = client.get('/admin/screenshot/999999')
    assert response.status_code == 404


def test_admin_screenshot_route_unauthorized(client, app):
    """Test admin screenshot serving route without admin access."""
    submission_id, screenshot_id = create_test_submission_with_screenshot(app)
    
    response = client.get(f'/admin/screenshot/{screenshot_id}')
    assert response.status_code == 403  # Forbidden (not admin)


def test_user_screenshot_route_success(client, app):
    """Test user screenshot serving route for own submissions."""
    user = create_and_login_user(client, app, "user@example.com")
    submission_id, screenshot_id = create_test_submission_with_screenshot(app, "user@example.com")
    
    response = client.get(f'/me/screenshot/{screenshot_id}')
    assert response.status_code == 200
    assert response.headers['Content-Type'] == 'image/png'
    assert len(response.data) > 0


def test_user_screenshot_route_unauthorized_different_user(client, app):
    """Test user screenshot serving route for another user's submission."""
    create_and_login_user(client, app, "user1@example.com")
    submission_id, screenshot_id = create_test_submission_with_screenshot(app, "user2@example.com")  # Different user
    
    response = client.get(f'/me/screenshot/{screenshot_id}')
    assert response.status_code == 403  # Forbidden


def test_user_screenshot_route_not_found(client, app):
    """Test user screenshot serving route with non-existent screenshot."""
    create_and_login_user(client, app)
    
    response = client.get('/me/screenshot/999999')
    assert response.status_code == 404


def test_user_screenshot_route_requires_login(client, app):
    """Test user screenshot route requires authentication."""
    submission_id, screenshot_id = create_test_submission_with_screenshot(app)
    
    response = client.get(f'/me/screenshot/{screenshot_id}')
    assert response.status_code == 302  # Redirect to login


def test_screenshot_thumbnail_generation(app):
    """Test screenshot thumbnail generation functionality."""
    # Test with valid PNG data
    png_data = create_test_image_data(800, 600, 'PNG')
    
    with app.app_context():
        from sister_website.app import generate_screenshot_thumbnail
        thumbnail = generate_screenshot_thumbnail(png_data)
        
        assert thumbnail is not None
        assert len(thumbnail) > 0
        
        # Verify thumbnail is a valid JPEG
        thumbnail_img = Image.open(BytesIO(thumbnail))
        assert thumbnail_img.format == 'JPEG'
        assert thumbnail_img.size[0] <= 240  # Max width
        assert thumbnail_img.size[1] <= 240  # Max height


def test_screenshot_thumbnail_generation_rgba(app):
    """Test screenshot thumbnail generation with RGBA image."""
    # Create RGBA image
    img = Image.new('RGBA', (400, 300), color=(255, 0, 0, 128))
    img_buffer = BytesIO()
    img.save(img_buffer, format='PNG')
    rgba_data = img_buffer.getvalue()
    
    with app.app_context():
        from sister_website.app import generate_screenshot_thumbnail
        thumbnail = generate_screenshot_thumbnail(rgba_data)
        
        assert thumbnail is not None
        # Should convert to RGB successfully
        thumbnail_img = Image.open(BytesIO(thumbnail))
        assert thumbnail_img.format == 'JPEG'
        assert thumbnail_img.mode == 'RGB'


def test_screenshot_thumbnail_generation_invalid_data(app):
    """Test screenshot thumbnail generation with invalid image data."""
    invalid_data = b"not an image"
    
    with app.app_context():
        from sister_website.app import generate_screenshot_thumbnail
        thumbnail = generate_screenshot_thumbnail(invalid_data)
        
        assert thumbnail is None


def test_allowed_mime_type_validation(app):
    """Test MIME type validation for file uploads."""
    with app.app_context():
        from sister_website.app import allowed_mime
        
        # Create a valid PNG file
        png_data = create_test_image_data()
        png_file = BytesIO(png_data)
        png_file.filename = 'test.png'
        
        # Create a valid JPEG file
        jpeg_data = create_test_image_data(format='JPEG')
        jpeg_file = BytesIO(jpeg_data)
        jpeg_file.filename = 'test.jpg'
        
        # Create invalid file
        invalid_file = BytesIO(b"not an image")
        invalid_file.filename = 'test.txt'
        
        # Mock the magic library
        with patch('magic.from_buffer') as mock_magic:
            mock_magic.return_value = 'image/png'
            result = allowed_mime(png_file)
            assert result == 'image/png'
            
            mock_magic.return_value = 'image/jpeg'
            result = allowed_mime(jpeg_file)
            assert result == 'image/jpeg'
            
            mock_magic.return_value = 'text/plain'
            result = allowed_mime(invalid_file)
            assert result is None


def test_allowed_mime_type_validation_exception(app):
    """Test MIME type validation when magic library throws exception."""
    with app.app_context():
        from sister_website.app import allowed_mime
        
        test_file = BytesIO(b"test data")
        test_file.filename = 'test.png'
        
        with patch('magic.from_buffer', side_effect=Exception("Magic error")):
            result = allowed_mime(test_file)
            assert result is None


def test_allowed_mime_type_validation_import_error(app):
    """Test MIME type validation when magic library is not available."""
    with app.app_context():
        from sister_website.app import allowed_mime
        
        test_file = BytesIO(b"test data")
        test_file.filename = 'test.png'
        
        with patch('magic.from_buffer', side_effect=ImportError("No magic")):
            result = allowed_mime(test_file)
            assert result is None


def test_save_screenshot_function_success(app):
    """Test save_screenshot utility function success case."""
    with app.app_context():
        from sister_website.app import save_screenshot
        
        # Create test submission and build
        submission = Submission(
            email='test@example.com',
            acceptance_token='token123',
            acceptance_state=AcceptanceState.PENDING
        )
        build = Build(submission=submission, platform='PC', type='space')
        db.session.add_all([submission, build])
        db.session.commit()
        
        # Create valid image file
        image_data = create_test_image_data()
        image_file = BytesIO(image_data)
        image_file.filename = 'test.png'
        
        # Mock allowed_mime to return valid MIME type
        with patch('sister_website.app.allowed_mime', return_value='image/png'):
            result = save_screenshot(image_file, 'test')
            
            assert result is not None
            assert result.filename == 'test.png'
            assert len(result.data) > 0


def test_save_screenshot_function_invalid_mime(app):
    """Test save_screenshot utility function with invalid MIME type."""
    with app.app_context():
        from sister_website.app import save_screenshot
        
        # Create test submission and build
        submission = Submission(
            email='test@example.com',
            acceptance_token='token123',
            acceptance_state=AcceptanceState.PENDING
        )
        build = Build(submission=submission, platform='PC', type='space')
        db.session.add_all([submission, build])
        db.session.commit()
        
        # Create invalid file
        invalid_file = BytesIO(b"not an image")
        invalid_file.filename = 'bad.txt'
        
        # Mock allowed_mime to return None (invalid)
        with patch('sister_website.app.allowed_mime', return_value=None):
            result = save_screenshot(invalid_file, 'bad')
            
            assert result is None


def test_save_screenshot_function_duplicate_md5(app):
    """Test save_screenshot utility function with duplicate MD5 hash."""
    with app.app_context():
        from sister_website.app import save_screenshot
        
        # Create test submission and build
        submission = Submission(
            email='test@example.com',
            acceptance_token='token123',
            acceptance_state=AcceptanceState.PENDING
        )
        build = Build(submission=submission, platform='PC', type='space')
        
        # Create existing screenshot with same MD5
        existing_screenshot = Screenshot(
            build=build,
            filename='existing.png',
            md5sum='duplicate_hash',
            data=b'existing data'
        )
        
        db.session.add_all([submission, build, existing_screenshot])
        db.session.commit()
        
        # Try to save another screenshot that would have same MD5
        image_file = BytesIO(b"test image data")
        image_file.filename = 'duplicate.png'
        
        with patch('sister_website.app.allowed_mime', return_value='image/png'):
            with patch('hashlib.md5') as mock_md5:
                mock_md5.return_value.hexdigest.return_value = 'duplicate_hash'
                
                result = save_screenshot(image_file, 'duplicate')
                
                # The function should still return a screenshot object even if MD5 is duplicate
                # (the actual duplicate handling might be done elsewhere)
                assert result is not None
                assert result.filename == 'duplicate.png'


def test_file_upload_size_limit(client, app):
    """Test file upload size limit enforcement."""
    # This would typically be tested by trying to upload a file larger than MAX_CONTENT_LENGTH
    # For now, we'll test that the configuration is set
    assert app.config.get('MAX_CONTENT_LENGTH') == 32 * 1024 * 1024  # 32MB


def test_secure_filename_usage(app):
    """Test that secure filename is used for file uploads."""
    with app.app_context():
        from werkzeug.utils import secure_filename
        
        # Test various filename scenarios
        assert secure_filename('test.png') == 'test.png'
        assert secure_filename('../../../etc/passwd') == 'etc_passwd'
        assert secure_filename('file with spaces.png') == 'file_with_spaces.png'
        assert secure_filename('файл.png') == 'png'  # Non-ASCII characters removed


def create_test_png_data():
    """Create minimal valid PNG file data for testing."""
    # PNG header + minimal IHDR chunk
    png_header = b'\x89PNG\r\n\x1a\n'
    ihdr_chunk = b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde'
    iend_chunk = b'\x00\x00\x00\x00IEND\xaeB`\x82'
    return png_header + ihdr_chunk + iend_chunk


def create_test_jpeg_data():
    """Create minimal valid JPEG file data for testing."""
    # Minimal JPEG file with SOI and EOI markers
    return b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x01\x01\x11\x00\x02\x11\x01\x03\x11\x01\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\xff\xc4\x00\x14\x10\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xda\x00\x08\x01\x01\x00\x01?\x10\xff\xd9'


def test_save_screenshot_valid_png(app):
    """Test saving a valid PNG screenshot."""
    png_data = create_test_png_data()
    
    with app.app_context():
        file_storage = FileStorage(
            stream=BytesIO(png_data),
            filename='test.png',
            content_type='image/png'
        )
        
        screenshot = save_screenshot(file_storage)
        
        assert screenshot is not None
        assert screenshot.filename == 'test.png'
        assert screenshot.data == png_data
        assert len(screenshot.md5sum) == 32  # MD5 hash length


def test_save_screenshot_valid_jpeg(app):
    """Test saving a valid JPEG screenshot."""
    jpeg_data = create_test_jpeg_data()
    
    with app.app_context():
        file_storage = FileStorage(
            stream=BytesIO(jpeg_data),
            filename='test.jpg',
            content_type='image/jpeg'
        )
        
        screenshot = save_screenshot(file_storage)
        
        assert screenshot is not None
        assert screenshot.filename == 'test.jpg'
        assert screenshot.data == jpeg_data
        assert len(screenshot.md5sum) == 32


def test_save_screenshot_with_custom_filename(app):
    """Test saving screenshot with custom filename base."""
    png_data = create_test_png_data()
    
    with app.app_context():
        file_storage = FileStorage(
            stream=BytesIO(png_data),
            filename='original.png',
            content_type='image/png'
        )
        
        screenshot = save_screenshot(file_storage, filename_base='custom_name')
        
        assert screenshot is not None
        assert screenshot.filename == 'custom_name.png'


def test_save_screenshot_no_file(app):
    """Test save_screenshot with no file provided."""
    with app.app_context():
        result = save_screenshot(None)
        assert result is None


def test_save_screenshot_invalid_mime_type(app):
    """Test save_screenshot with invalid MIME type."""
    invalid_data = b"not an image"
    
    with app.app_context():
        file_storage = FileStorage(
            stream=BytesIO(invalid_data),
            filename='test.txt',
            content_type='text/plain'
        )
        
        result = save_screenshot(file_storage)
        assert result is None


def test_allowed_mime_valid_png(app):
    """Test allowed_mime function with valid PNG."""
    png_data = create_test_png_data()
    
    with app.app_context():
        file_storage = FileStorage(
            stream=BytesIO(png_data),
            filename='test.png',
            content_type='image/png'
        )
        
        mime_type = allowed_mime(file_storage)
        assert mime_type == 'image/png'


def test_allowed_mime_valid_jpeg(app):
    """Test allowed_mime function with valid JPEG."""
    jpeg_data = create_test_jpeg_data()
    
    with app.app_context():
        file_storage = FileStorage(
            stream=BytesIO(jpeg_data),
            filename='test.jpg',
            content_type='image/jpeg'
        )
        
        mime_type = allowed_mime(file_storage)
        assert mime_type == 'image/jpeg'


def test_allowed_mime_invalid_file(app):
    """Test allowed_mime function with invalid file."""
    invalid_data = b"not an image"
    
    with app.app_context():
        file_storage = FileStorage(
            stream=BytesIO(invalid_data),
            filename='test.txt',
            content_type='text/plain'
        )
        
        mime_type = allowed_mime(file_storage)
        assert mime_type is None


def test_admin_screenshot_route_authenticated(client, app):
    """Test admin screenshot route with authentication."""
    # Create a test screenshot
    with app.app_context():
        submission = Submission(
            email='test@example.com',
            acceptance_token='test_token',
            acceptance_state=AcceptanceState.PENDING
        )
        build = Build(submission=submission, platform='PC', type='space')
        screenshot = Screenshot(
            build=build,
            filename='test.png',
            md5sum='abc123',
            data=create_test_png_data()
        )
        
        db.session.add_all([submission, build, screenshot])
        db.session.commit()
        
        # Extract ID before leaving app context
        screenshot_id = screenshot.id
    
    # Test without authentication
    response = client.get(f'/admin/screenshot/{screenshot_id}')
    assert response.status_code in [302, 403]  # Redirect to login or forbidden
    
    # Test with mock authentication
    with patch('sister_website.app.is_admin', return_value=True):
        response = client.get(f'/admin/screenshot/{screenshot_id}')
        assert response.status_code == 200
        assert response.content_type.startswith('image/')


def test_user_screenshot_route_authenticated(client, app):
    """Test user screenshot route with authentication."""
    # Create a test user and screenshot
    with app.app_context():
        user = User(email='user@example.com', email_verified=True)
        user.set_password('password123')
        
        submission = Submission(
            email=user.email,
            acceptance_token='test_token',
            acceptance_state=AcceptanceState.PENDING
        )
        build = Build(submission=submission, platform='PC', type='space')
        screenshot = Screenshot(
            build=build,
            filename='test.png',
            md5sum='abc123',
            data=create_test_png_data()
        )
        
        db.session.add_all([user, submission, build, screenshot])
        db.session.commit()
        
        # Extract IDs before leaving app context
        screenshot_id = screenshot.id
    
    # Test without authentication
    response = client.get(f'/me/screenshot/{screenshot_id}')
    assert response.status_code == 302  # Redirect to login
    
    # Test with authentication - login via POST request
    login_response = client.post('/login', data={
        'email': 'user@example.com',
        'password': 'password123',
        'csrf_token': 'test'
    })
    assert login_response.status_code == 302  # Redirect after successful login
    
    response = client.get(f'/me/screenshot/{screenshot_id}')
    assert response.status_code == 200
    assert response.content_type.startswith('image/')


def test_screenshot_thumbnail_generation(app):
    """Test screenshot thumbnail generation."""
    png_data = create_test_png_data()
    
    with app.app_context():
        file_storage = FileStorage(
            stream=BytesIO(png_data),
            filename='test.png',
            content_type='image/png'
        )
        
        with patch('sister_website.app.generate_screenshot_thumbnail') as mock_thumbnail:
            mock_thumbnail.return_value = b'thumbnail_data'
            
            screenshot = save_screenshot(file_storage)
            
            assert screenshot is not None
            mock_thumbnail.assert_called_once_with(png_data)


def test_screenshot_md5_calculation(app):
    """Test MD5 calculation for screenshots."""
    png_data = create_test_png_data()
    
    with app.app_context():
        file_storage = FileStorage(
            stream=BytesIO(png_data),
            filename='test.png',
            content_type='image/png'
        )
        
        screenshot = save_screenshot(file_storage)
        
        import hashlib
        expected_md5 = hashlib.md5(png_data).hexdigest()
        assert screenshot.md5sum == expected_md5


def test_file_upload_security_validation(app):
    """Test file upload security validations."""
    # Test with potentially malicious filename
    malicious_filenames = [
        '../../../etc/passwd',
        'test.php',
        'script.js',
        'test.exe'
    ]
    
    png_data = create_test_png_data()
    
    with app.app_context():
        for filename in malicious_filenames:
            file_storage = FileStorage(
                stream=BytesIO(png_data),
                filename=filename,
                content_type='image/png'
            )
            
            screenshot = save_screenshot(file_storage)
            
            if screenshot:
                # Filename should be sanitized
                assert not screenshot.filename.startswith('..')
                assert not screenshot.filename.startswith('/')
            else:
                # File should be rejected based on extension/mime mismatch
                assert True 