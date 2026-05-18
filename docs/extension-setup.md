# VisionVolve Leads — Chrome Extension Setup

The VisionVolve Leads extension is a Chromium-based browser extension that
turns LinkedIn into a CRM workspace.

## What it does

- **Lead import**: extracts contact and company details from LinkedIn Sales
  Navigator search results and pushes them into your VisionVolve workspace.
- **Activity capture**: records messages, connection requests, and feed
  interactions so they show up against the right contact.
- **In-page validation**: when you open a LinkedIn profile or company page,
  the side panel shows the matching CRM record and flags any data
  mismatches (title, headquarters, website, etc.).
- **Side panel**: log in once, switch namespaces, see queued LinkedIn
  actions, and trigger ad-hoc imports.

Supported LinkedIn surfaces (see `extension/manifests/base.json` for the
authoritative list):

| Surface                          | Capability                          |
|----------------------------------|-------------------------------------|
| `linkedin.com/sales/*`           | Lead extraction (Sales Navigator)   |
| `linkedin.com/messaging/*`       | Activity capture                    |
| `linkedin.com/mynetwork/*`       | Activity capture                    |
| `linkedin.com/feed/*`            | Activity capture                    |
| `linkedin.com/in/*`              | Profile validation                  |
| `linkedin.com/company/*`         | Company validation                  |

## Install

The fastest path is the self-serve download in the dashboard:

1. Sign in to the dashboard at
   `https://leadgen.visionvolve.com/{namespace}/` (or your own staging URL).
2. Open **Settings → Browser Extension**.
3. Click **Download Production Extension**. Your browser downloads
   `visionvolve-leads-prod-v{version}.zip`.
4. Unzip the file to a folder you will keep around (the extension is loaded
   directly from disk).
5. In Chrome, open `chrome://extensions`.
6. Enable **Developer mode** using the toggle in the top right.
7. Click **Load unpacked** and select the unzipped folder.
8. Pin the extension to the toolbar (puzzle-piece menu → pin).
9. Click the extension icon to open the side panel and log in with your
   VisionVolve credentials.

Super admins can also download the staging build (which talks to
`leadgen-staging.visionvolve.com`) from the same screen. Use this when you
want to dogfood unreleased server behaviour without touching production.

## Verify it's working

After installing the extension and logging in:

1. Open `https://www.linkedin.com/sales/` and run a search.
2. The side panel should populate with the search results and offer to
   import them.
3. Go back to **Settings → General** in the dashboard. The "Browser
   Extension" card should report **Connected**, with non-zero values for
   leads imported and activities synced.
4. Hit the status endpoint directly to confirm round-trip auth works:
   ```
   GET /api/extension/status
   Authorization: Bearer <token>
   X-Namespace: <namespace>
   ```
   You should see `{"connected": true, ...}`.

## Troubleshooting

### "Load unpacked" greyed out

Make sure **Developer mode** is enabled. Without it, Chrome refuses to load
unsigned extensions.

### Extension loads but the side panel never opens

Some Chromium derivatives (Brave, Arc) hide the side panel by default. Try
the keyboard shortcut for "Open side panel" or use stock Chrome to confirm
the build works.

### CORS errors in the side panel

The extension manifests declare `host_permissions` for
`leadgen.visionvolve.com` (prod) and `leadgen-staging.visionvolve.com`
(staging). If you load the staging build but try to talk to production
(or vice versa) you will see CORS rejection. Re-download the correct
build for your environment.

### "Token expired" or repeated logouts

The extension uses the same JWT scheme as the dashboard. If your tokens
expire while the side panel is open, click **Log out** and sign in again
to capture a fresh refresh token.

### Wrong version installed

Check the version reported on `chrome://extensions` against the filename
you downloaded (e.g. `visionvolve-leads-prod-v1.0.0.zip`). If they differ
you may have an older folder still selected — re-run **Load unpacked**
on the freshly unzipped folder, then **Remove** the old entry.

## Updating

The extension is unsigned and not in the Chrome Web Store. To pick up a
new version:

1. Re-download from **Settings → Browser Extension**.
2. Unzip on top of the existing folder (or to a new folder and re-point
   the extension entry at it).
3. Click the **reload** icon for the extension on `chrome://extensions`.

## For developers

The dashboard download endpoint serves the same artifact that
`extension/scripts/build.sh` (or `npm run build:all` in `extension/`)
produces locally. The Docker image bakes both `dist/prod/` and
`dist/staging/` into `/app/extension/dist/{env}` during the API build
stage; the endpoint zips that directory on demand.

API contract:

```
GET /api/extension/download?env=prod|staging
Authorization: Bearer <token>

200 application/zip
Content-Disposition: attachment; filename="visionvolve-leads-{env}-v{version}.zip"
X-Extension-Version: <version>
```

Auth rules:

- `env=prod` (default): any authenticated user.
- `env=staging`: super admins only — returns 403 otherwise.
- Missing or invalid Bearer token: 401.
- Unknown `env` value: 400.
- Build not bundled in the container (e.g. local dev without
  `npm run build:all`): 404 with `{"error": "extension build not found: <env>"}`.

For local dev, set `EXTENSION_DIST_DIR=/absolute/path/to/extension/dist`
to point the endpoint at your locally-built `dist/`. Otherwise it tries
`/app/extension/dist/{env}` (container path) followed by the repo's
`extension/dist/{env}`.
