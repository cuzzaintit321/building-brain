# Building Brain — FacilityGuard (MVP)

FacilityGuard is an integrated operations module at **`/facilityguard`**. It uses the existing Building Brain property, building, equipment and authentication system. It is **not a separate SaaS**, and no second database or deployment is required.

## Included

- **Work orders:** create, prioritize, assign, set due dates, and progress through open, in progress, blocked, completed or cancelled states.
- **Preventive maintenance:** recurring task plans linked to buildings and optionally equipment; record completions, technician and notes, and automatically advance the next due date by the configured interval.
- **Inspections:** record checklist, date, inspector, findings and pass/fail/needs-attention status; failed inspections can open linked-context corrective work orders.
- **Operations dashboard:** counts for open and overdue work orders, due and upcoming PM, pending and failed inspections.
- **CSV export:** consolidated property-scoped CSV report with work orders, plans and inspections.
- **Safety and data isolation:** authenticated via the existing Building Brain middleware; all records are checked for the selected property, building and optional equipment asset; unknown or cross-property records are rejected.

## Deployment

After updating the existing Building Brain checkout, use the **existing** Docker stack and persistent volume:

```bash
cd ~/building-brain   # or your existing clone location
# back up your SQLite database / persistent Docker volume before upgrading
git pull --ff-only
docker compose up -d --build
```

Open the normal Building Brain interface, sign in, then click **FacilityGuard**. The new SQLite tables are created automatically on startup. Existing data and tables are retained. Do not delete or recreate your persistent volume.

## API

| Method | URL | Function |
|---|---|---|
| GET | `/api/facilityguard/overview?property_id=1` | Dashboard statistics |
| GET/POST | `/api/facilityguard/work-orders` | List/create work orders |
| PATCH | `/api/facilityguard/work-orders/{id}?property_id=1` | Update work-order status |
| GET/POST | `/api/facilityguard/pm-plans` | List/create PM plans |
| POST | `/api/facilityguard/pm-plans/{id}/complete?property_id=1` | Record a PM completion |
| GET | `/api/facilityguard/pm-plans/{id}/history?property_id=1` | PM completion history |
| GET/POST | `/api/facilityguard/inspections` | List/create inspections |
| POST | `/api/facilityguard/inspections/{id}/complete?property_id=1` | Record inspection results, optional corrective work order |
| GET | `/api/facilityguard/report.csv?property_id=1` | Download a property-scoped report |

GET list endpoints accept an optional `building_id` filter. POST endpoints require `property_id` and `building_id`. Authentication applies to every request; the demo uses Basic Auth.

## Boundaries

This release is a **single-organization MVP**, not an audited enterprise CMMS. It does **not** yet include photo uploads, PDF reports, signed inspection attestations, calendar integrations, scheduled notifications, automated job dispatch, vendor COI tracking, granular roles, immutable compliance audit history, or AI regulatory determinations. Asset management reuses the existing Building Brain equipment registry. Inspection checklists are presently free-text, not structured question-by-question forms.

The counts and inspection records show work performed or recorded; **they do not certify compliance** with any building, fire, healthcare, or safety regulation. The existing Basic Auth mechanism is suitable only for a trusted deployment. Add SSO, permissions, backups, retention rules, monitoring, robust audit trails and penetration testing before commercial multi-customer hosting.
