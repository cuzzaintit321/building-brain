import os
import sqlite3
import tempfile
import unittest
from fastapi import HTTPException

tmp=tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_DIR",tmp.name)
os.environ.setdefault("SECRET_KEY","test-secret")
os.environ.setdefault("ADMIN_PASSWORD","test-password")
from backend import main
from backend.billing import enforce_quota

class PlanLimitsTests(unittest.TestCase):
    def test_property_limit(self):
        with sqlite3.connect(":memory:") as c:
            c.execute("CREATE TABLE properties(id INTEGER)")
            for i in range(5):
                enforce_quota(c,"properties","starter")
                c.execute("INSERT INTO properties VALUES(?)",(i,))
            with self.assertRaises(HTTPException) as e:
                enforce_quota(c,"properties","starter")
            self.assertEqual(e.exception.status_code,409)
            enforce_quota(c,"properties","professional")

    def test_unknown_plan(self):
        with sqlite3.connect(":memory:") as c:
            with self.assertRaises(HTTPException):
                enforce_quota(c,"properties","unknown")
