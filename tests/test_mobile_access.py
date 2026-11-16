import os, tempfile, unittest
from fastapi.testclient import TestClient
from app.main import app
from app.db import db
class MobileAccessTests(unittest.TestCase):
    def test_scoping_and_revocation(self):
        with tempfile.TemporaryDirectory() as directory:
            old=os.environ.copy()
            os.environ.update(DATA_DIR=directory,APP_USER='admin',APP_PASSWORD='test-admin-password')
            try:
                with TestClient(app) as client:
                    with db() as c:
                        c.execute("INSERT INTO properties(id,name) VALUES(1,'One'),(2,'Two')")
                    data=dict(username='tech',password='test-tech-password',property_id=1,role='viewer')
                    self.assertEqual(client.post('/api/mobile/admin/accounts',json=data).status_code,401)
                    account=client.post('/api/mobile/admin/accounts',json=data,auth=('admin','test-admin-password'))
                    self.assertEqual(account.status_code,200)
                    token=client.post('/api/mobile/login',json=data).json()['token']
                    headers={'Authorization':'Bearer '+token}
                    self.assertEqual(client.get('/api/mobile/properties/2/assets',headers=headers).status_code,403)
                    self.assertEqual(client.get('/api/overview',headers=headers).status_code,401)
                    self.assertEqual(client.patch('/api/mobile/properties/1/work-orders/1',headers=headers,json={'status':'completed','expected_status':'open'}).status_code,403)
                    client.post('/api/mobile/logout',headers=headers)
                    self.assertEqual(client.get('/api/mobile/properties',headers=headers).status_code,401)
            finally:
                os.environ.clear()
                os.environ.update(old)
