![Building Brain 3.0 Connect — product roadmap concept](https://github.com/cuzzaintit321/building-brain/raw/8bfaae92ecb3466fc45a43693a4d4fb6045ea218/assets/cover.png)

*Building Brain 3.0 Connect — product vision; the current implementation is described below.*

# Building Brain 2.0

A mobile-first, self-hosted maintenance workspace: properties, assets, work orders, preventive maintenance, field notes/photos, document indexing, and a document-grounded assistant.

## Included and working

- Responsive Android/desktop interface, installable PWA shell
- Password-protected single-admin workspace (signed session cookie)
- Separate properties and equipment inventory with location/serial/warranty data
- Work order creation, editing, prioritization, assignment, completion
- Scheduled preventive maintenance; completing tasks advances next due date
- PDF, DOCX, TXT, Markdown searchable document upload, download and deletion
- Asset/field note search with attributed excerpts even **without** an AI key
- Optional OpenAI Responses API synthesis constrained to source excerpts and citations
- Field technician notes with photos (camera/file upload)
- SQLite persistence stored in mounted `data/` directory
- Sample demo property and sample data (replace with verified property records)

## Deploy on yeet (Ubuntu, Docker Compose)

```bash
unzip building-brain-2.zip
cd building-brain-2
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_hex(32))'  # copy into SECRET_KEY
nano .env   # replace both ADMIN_PASSWORD and SECRET_KEY
mkdir -p data
sudo chown -R 10001:10001 data
chmod 600 .env
docker compose up -d --build
docker compose ps
```

Desktop on LAN: `http://192.168.1.130:8124` assuming yeet retains that IP. Phone on same Wi-Fi: same URL (test mobile browser). For home-screen PWA installation, **HTTPS is required** except for localhost. Publish via your existing Caddy reverse proxy with TLS and configure `COOKIE_SECURE=true` after testing HTTPS. Do not expose port 8124 publicly; close WAN port forwarding and use TLS reverse proxy, VPN, or Tailscale. Example Caddy reverse proxy snippet (add to the Caddyfile serving your domain, assuming Caddy and Building Brain can reach each other):

```caddyfile
brain.jasonpauledwards.com {
    reverse_proxy 192.168.1.130:8124
}
```

Configure DNS so the hostname resolves to your home connection, and authorize access securely before exposing it on the internet. Test only once you control DNS, Caddy networking, and firewall. HTTPS with a strong password is the minimum; for production add MFA, user accounts and rate-limiting (not in this MVP). Existing Caddy config may require a different upstream host or Docker network.

**Optional AI:** Add `OPENAI_API_KEY` to `.env`. The key is sent from your server to OpenAI only for `/api/ask` requests with matched source excerpts; uploaded files remain in local storage unless relevant snippets are included in an AI request. By default the app returns matched excerpts locally instead. Upload only documents you are authorized to use. The assistant does not know your property unless you enter its data.

**Important security & operational boundaries:** This is a development MVP, not a safety-certified CMMS. Use verified plans and qualified personnel for electrical isolation, confined spaces, gas systems, and emergency shutoffs. Single-admin sign-in has no brute-force protection, password reset, audit trail, or role permissions. PWA shell caches layout files, not authenticated API data; offline record editing is not supported. The app does not scan QR codes or interpret CAD natively yet. It is not fully multi-tenant SaaS.

## Manage / backup

```bash
docker compose logs -f building-brain
docker compose down
# Back up data/ while app is stopped or use SQLite's online backup API.
tar czf building-brain-data-backup.tar.gz data/
```

### Planned next upgrades
- Verified QR asset labels + scanner
- PDF viewer with source page citation and plan annotations
- Multi-user access and roles, SSO / MFA, audit logs
- PM templates, analytics, asset-history timeline, alerts
- Object storage and multi-tenant PostgreSQL SaaS deployment


## Property GPS recognition

Use **Property GPS settings** in the sidebar (or mobile More menu) to save the property's center latitude, longitude and geofence radius (25–2000 meters). You can use your device's current location to populate the center, or enter coordinates manually. Existing property records are migrated automatically without adding fake coordinates.

Select **Detect property** to find the matching property. A single high-confidence match switches to its overview; overlapping or uncertain matches require confirmation. Inaccurate or out-of-range locations never switch properties. Enable automatic detection on sign-in/opening the app in GPS settings if desired; the preference stays on the current browser. Browser geolocation requires HTTPS, user permission and a compatible device. Indoor GPS and circular boundaries are approximate, so manually confirm questionable results. No continuous tracking, location history, external geocoding, or live technician location upload is implemented. Only explicitly saved property centers are sent to the backend. The separate legacy `app/` implementation is unchanged; Docker uses `backend/main.py` and `static/`.

Run the location matching unit tests with `node --test tests/test_geolocation.cjs`.

## Train a property: brand and model knowledge

Open **Property Knowledge** (mobile: More) to see the brand registry automatically assembled from equipment manufacturers and model numbers. Add lessons using **Teach Brain**, either in the library or directly from an equipment record. Record the brand, exact model, equipment category, type, content and source (manual title/page, verified repair record, manufacturer document, etc.). New lessons are drafts until marked approved with a source. Edit or remove lessons at any time. No manufacturer or repair facts are pre-populated.

Ask Brain can now retrieve approved property knowledge and completed work-order resolutions in addition to existing documents, assets and field notes. Choose an asset in the AI screen to prioritize its exact model and associated repairs. Model-specific knowledge without an asset is matched only when an exact model identifier appears in the question. Brand-level knowledge is not a substitute for model-specific instructions; check manufacturer documentation. Records are scoped to the selected property; this is retrieval-augmented memory, not model-weight training. Raw manuals are still searchable property-wide, and AI must verify applicability to the selected model. No automatic internet scraping or independent source verification is performed.

The knowledge table is created automatically on existing databases. Test the Docker backend with `pytest -q tests/test_property_knowledge.py` (install requirements-dev.txt first).
