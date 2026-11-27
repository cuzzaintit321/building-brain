import tempfile
import unittest
import sqlite3
from backend.organizations import Registry

class OrganizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.registry = Registry(self.tmp.name)
        self.a, self.u = self.registry.create_organization("A","a@example.test","long-password-a")
        self.b, self.v = self.registry.create_organization("B","b@example.test","long-password-b")

    def test_login(self):
        self.assertEqual(self.registry.authenticate("A@example.test","long-password-a"),self.u)
        self.assertIsNone(self.registry.authenticate("a@example.test","wrong"))

    def test_membership(self):
        self.assertEqual(self.registry.role(self.u,self.a),"owner")
        self.assertIsNone(self.registry.role(self.u,self.b))
        with self.assertRaises(PermissionError):
            self.registry.workspace(self.u,self.b)

    def test_separate_paths(self):
        self.assertNotEqual(self.registry.workspace(self.u,self.a),self.registry.workspace(self.v,self.b))

    def test_duplicate_email_rolls_back(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.registry.create_organization("Duplicate","a@example.test","long-password-c")
        with self.registry.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM organizations").fetchone()[0],2)

    def test_invitation_single_use(self):
        token=self.registry.invite(self.u,self.a,"employee@example.test","member")
        oid,uid=self.registry.accept_invitation(token,"employee-password")
        self.assertEqual(oid,self.a)
        self.assertEqual(self.registry.role(uid,oid),"member")
        with self.assertRaises(ValueError):
            self.registry.accept_invitation(token,"employee-password")
        with self.assertRaises(PermissionError):
            self.registry.invite(uid,oid,"other@example.test","admin")
