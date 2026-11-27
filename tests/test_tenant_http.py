import os
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

tmp=tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_DIR",tmp.name)
os.environ.setdefault("SECRET_KEY","test-secret")
os.environ.setdefault("ADMIN_PASSWORD","test-password")
from backend import main

class TenantHTTPTests(unittest.TestCase):
    def test_isolation(self):
        with tempfile.TemporaryDirectory() as root, patch.object(main,"REGISTRY",main.Registry(root)), patch.dict(os.environ,{"TENANT_PILOT_ENABLED":"true","SUBSCRIPTION_ENFORCEMENT":"false","BILLING_PUBLIC_URL":"https://testserver"}):
            a,u=main.REGISTRY.create_organization("A","a@example.test","password-for-a")
            b,v=main.REGISTRY.create_organization("B","b@example.test","password-for-b")
            with TestClient(main.app,base_url="https://testserver") as ca, TestClient(main.app,base_url="https://testserver") as cb:
                for client,email,pw,oid in [(ca,"a@example.test","password-for-a",a),(cb,"b@example.test","password-for-b",b)]:
                    self.assertEqual(client.post("/api/tenant/login",json={"email":email,"password":pw,"organization_id":oid}).status_code,200)
                self.assertEqual(ca.post("/api/properties",json={"name":"Private A"},headers={"Origin":"https://testserver"}).status_code,200)
                self.assertEqual(cb.get("/api/properties").json(),[])
                self.assertEqual(ca.get("/api/properties").json()[0]["name"],"Private A")
                with main.REGISTRY.connect() as c:
                    c.execute("UPDATE users SET password_hash='revoked' WHERE id=?",(u,))
                self.assertEqual(ca.get("/api/properties").status_code,401)
