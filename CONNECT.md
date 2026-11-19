# Building Brain Connect — implementation status

The canonical Docker backend now mounts /api/connect. Existing admin cookie authentication provisions technicians and assigns existing orders. Technician bearer sessions can list assigned orders and submit progress or completion with a revision and resolution. The admin activity endpoint returns the event history. This is a single-company development foundation, not tenant-isolated SaaS.

## API
- POST /api/connect/admin/users {username,password,property_ids}
- GET /api/connect/admin/users
- DELETE /api/connect/admin/users/{id}
- PUT /api/connect/admin/orders/{id}/assign {user_id}
- POST /api/connect/login {username,password}
- GET /api/connect/orders (Bearer token)
- PATCH /api/connect/orders/{id} {status,revision,resolution}
- POST /api/connect/logout
- GET /api/connect/admin/activity?after=0

## Release gates
- Reconcile existing admin order edits with assignment revisions and event history.
- Add tenant-scoped PostgreSQL schema and role-based management authentication; migrate all existing APIs and uploads.
- Build supervisor UI and native Tauri shell; connect React Native client to canonical API.
- Add secure real-time events, offline queue, photos, QR, AI, inventory, inspections, notifications, billing.
- Add integration tests, CSRF protection for admin mutations, distributed rate limits, device tests, security review and backup/restore.
- Do not deploy as public multi-tenant SaaS until these gates pass.

## Communications development prototype

Create individual employee accounts (including a separate supervisor account) via the existing admin account endpoint and assign at least one common property. Open /static/communications.html on two devices, sign in with different accounts, select a contact and send a message or place a voice/video call. Incoming calls require explicit acceptance. /static/quick-share.html sends photos to the administrator without a work order; the management sidebar has a team photo feed.

Signaling uses authenticated HTTP polling, not WebSockets yet. Calls are limited to active accounts sharing an authorized property. The existing single-admin account is not itself a calling identity. Browser media requires HTTPS or localhost and user permission. No native mobile or desktop packaging, background ringing, group chat, screen sharing, or recording is implemented.

### TURN configuration

Run a separately secured Coturn instance with a public address, TLS certificate, authentication secret, relay port range, and firewall rules. Pass CONNECT_STUN_URLS and CONNECT_TURN_URLS as comma-separated URL lists into the Building Brain container; pass CONNECT_TURN_SECRET via protected environment configuration. The secret must match Coturn's static-auth-secret with use-auth-secret enabled. The API issues temporary HMAC credentials; never expose the shared secret to clients. Without configured TURN, calls may fail across NATs. Do not expose an unauthenticated TURN relay.

Required before release: integration and browser/device tests, call cleanup and reconnection, revocation behavior, abuse controls, CSRF mitigation, tenant isolation, privacy policy, storage quotas, and verified TURN deployment. No production service has been deployed.
