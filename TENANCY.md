# Tenant isolation migration

The identity registry in backend/organizations.py is an offline foundation, not a replacement for the current admin login. Public signup remains disabled.

Use a separate SQLite database and uploads directory per organization. Resolve the workspace from a server-validated user session and current membership on every request, never from an untrusted filesystem path. Refactor backend/main.py's global DB and UPLOADS into request-scoped accessors before enabling tenant sessions. Initialize each workspace without copying legacy data or demo records. Migrate existing data only through explicit operator-controlled migration.

Audit all property, asset, work order, preventive maintenance, document, note, photo, dashboard, knowledge and AI routes. Include cross-tenant IDs, file downloads, background work, caches and billing customer mapping. Owner/admin/member/viewer permissions must be enforced on the server. The registry currently stores roles but does not enforce route-level permissions.

Before public signup: add verified email, login rate limiting, session revocation, password reset, invitations, CSRF defenses, tenant-specific billing, entitlement checks and end-to-end cross-tenant tests. Keep Stripe in test mode until these gates pass.

Run the foundation tests with python -m unittest discover -s tests -p 'test_organizations.py'. Tests are not evidence of isolation in the legacy API.
