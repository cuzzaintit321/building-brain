import os
import tempfile
import unittest
import hashlib
import hmac

tmp = tempfile.TemporaryDirectory()
os.environ["DATA_DIR"] = tmp.name
os.environ["SECRET_KEY"] = "test-only-secret"
os.environ["ADMIN_PASSWORD"] = "test-only-password"
from backend.main import app
from backend.billing import verify_signature

class SignatureTests(unittest.TestCase):
    def setUp(self):
        self.payload = b'{"id":"evt_test"}'
        self.secret = "whsec_test"
        self.now = 100000
        digest = hmac.new(self.secret.encode(), str(self.now).encode()+b"."+self.payload, hashlib.sha256).hexdigest()
        self.header = f"t={self.now},v1={digest}"

    def test_valid(self):
        self.assertTrue(verify_signature(self.payload,self.header,self.secret,self.now))

    def test_modified_payload(self):
        self.assertFalse(verify_signature(b"{}",self.header,self.secret,self.now))

    def test_expired(self):
        self.assertFalse(verify_signature(self.payload,self.header,self.secret,self.now+301))

    def test_wrong_secret(self):
        self.assertFalse(verify_signature(self.payload,self.header,"wrong",self.now))

    def test_malformed(self):
        self.assertFalse(verify_signature(self.payload,"t=nope,v1=x",self.secret,self.now))

if __name__ == "__main__":
    unittest.main()
