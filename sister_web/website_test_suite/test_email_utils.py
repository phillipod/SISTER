import hashlib
import hmac

from sister_website.email_utils import verify_webhook_signature


def test_verify_webhook_signature_valid_and_invalid():
    key = "secret-key"
    payload = "sample-data"
    signature = hmac.new(key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    assert verify_webhook_signature(payload, signature, key)
    assert not verify_webhook_signature(payload, "bad" * 16, key)
    assert not verify_webhook_signature(None, signature, key)
