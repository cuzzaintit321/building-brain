import tempfile
import unittest
from backend.organizations import Registry
from backend.account_tokens import issue, consume

class TokenTests(unittest.TestCase):
    def test_purpose_and_replay(self):
        with tempfile.TemporaryDirectory() as root:
            registry=Registry(root)
            _,uid=registry.create_organization("Test","test@example.test","test-password-long")
            token=issue(registry,uid,"verify_email")
            seen=[]
            apply=lambda c,u:seen.append(u)
            self.assertFalse(consume(registry,token,"reset_password",apply))
            self.assertTrue(consume(registry,token,"verify_email",apply))
            self.assertFalse(consume(registry,token,"verify_email",apply))
            self.assertEqual(seen,[uid])
