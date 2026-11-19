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
