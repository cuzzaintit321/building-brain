import os
import tempfile
import unittest
from pathlib import Path

tmp = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_DIR", tmp.name)
os.environ.setdefault("SECRET_KEY", "test-only-secret")
os.environ.setdefault("ADMIN_PASSWORD", "test-only-password")
from backend import main

class WorkspaceStorageTests(unittest.TestCase):
    def test_separate_storage(self):
        with tempfile.TemporaryDirectory() as root:
            paths = [Path(root)/name for name in ("a","b")]
            for path in paths:
                path.mkdir()
                token = main.WORKSPACE.set(path)
                try:
                    main.init(seed_demo=False)
                    self.assertEqual(main.rows("SELECT * FROM properties"), [])
                    self.assertEqual(main.uploads_path(),path/"uploads")
                    if path == paths[0]:
                        with main.db() as c:
                            c.execute("INSERT INTO properties(name) VALUES(?)",("Private A",))
                        (main.uploads_path()/"private.txt").write_text("A")
                    else:
                        self.assertFalse((main.uploads_path()/"private.txt").exists())
                finally:
                    main.WORKSPACE.reset(token)
            self.assertNotEqual(paths[0]/"buildingbrain.db",paths[1]/"buildingbrain.db")
            self.assertEqual(main.database_path(),main.DB)
