"""Identity foundation; not connected to public registration or legacy routes."""
import hashlib
import hmac
import secrets
import sqlite3
import uuid
from pathlib import Path
from contextlib import contextmanager

class Registry:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.connect() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY, name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE,
                salt TEXT NOT NULL, password_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memberships (
                organization_id TEXT NOT NULL REFERENCES organizations(id),
                user_id TEXT NOT NULL REFERENCES users(id),
                role TEXT NOT NULL CHECK(role IN ('owner','admin','member','viewer')),
                PRIMARY KEY(organization_id,user_id)
            );
            """)

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.root / "identity.sqlite3", timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            with c:
                yield c
        finally:
            c.close()

    @staticmethod
    def password_hash(password, salt):
        return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                              n=2**15, r=8, p=1, maxmem=64*1024*1024).hex()

    def create_organization(self, name, email, password):
        name, email = name.strip(), email.strip().casefold()
        if not 1 <= len(name) <= 140 or not 3 <= len(email) <= 254 or "@" not in email:
            raise ValueError("Invalid organization or email")
        if not 12 <= len(password) <= 256:
            raise ValueError("Password must contain 12–256 characters")
        oid, uid = uuid.uuid4().hex, uuid.uuid4().hex
        salt = secrets.token_hex(16)
        digest = self.password_hash(password, salt)
        with self.connect() as c:
            c.execute("INSERT INTO organizations VALUES (?,?)", (oid,name))
            c.execute("INSERT INTO users VALUES (?,?,?,?)", (uid,email,salt,digest))
            c.execute("INSERT INTO memberships VALUES (?,?,?)", (oid,uid,"owner"))
        return oid, uid

    def authenticate(self, email, password):
        if len(password) > 256:
            return None
        with self.connect() as c:
            user = c.execute("SELECT * FROM users WHERE email=?", (email.strip().casefold(),)).fetchone()
        salt = user["salt"] if user else "0"*32
        digest = self.password_hash(password,salt)
        return user["id"] if user and hmac.compare_digest(digest,user["password_hash"]) else None

    def role(self, user_id, organization_id):
        with self.connect() as c:
            result = c.execute("SELECT role FROM memberships WHERE user_id=? AND organization_id=?", (user_id,organization_id)).fetchone()
        return result["role"] if result else None

    def workspace(self, user_id, organization_id):
        if not self.role(user_id, organization_id):
            raise PermissionError("Organization access denied")
        if uuid.UUID(hex=organization_id).hex != organization_id:
            raise ValueError("Invalid organization identifier")
        path = self.root / "workspaces" / organization_id
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        return path
