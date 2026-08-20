# Magewell AIO Control

Magewell AIO Control is a local Next.js and FastAPI utility for discovering Magewell
Ultra Encode AIO devices, reading one device as a control-settings source, applying
settings to explicitly selected targets, and planning guarded bulk device naming. It is
intended for a supervised local-network maintenance window, not as an unattended fleet
service.

The application is safe by default: it uses a loopback-only subnet and never scans on page
load. Profile writes require the device-write boundary; Naming uses a reviewed, identity-bound
plan plus the operator's explicit in-app confirmation.

## Prerequisites

- Docker Desktop (or Docker Engine) with Docker Compose v2
- For repository checks: Python 3.12+, Node.js 20+, npm, and
  [just](https://github.com/casey/just)
- A workstation connected to the intended local control network
- Valid Magewell credentials supplied at runtime

No credentials belong in Git. Credentials that appeared in earlier repository history
must be treated as exposed and rotated before a live run.

## Setup

1. Create the untracked runtime configuration:

   ```bash
   cp .env.example .env
   ```

2. Edit `.env`:

   - set `ALLOWED_SUBNET` to the smallest exact CIDR that contains the intended devices;
   - set `MAGEWELL_USERNAME` and `MAGEWELL_PASSWORD`;
   - keep `ENABLE_DEVICE_WRITES=false`, `ENABLE_CREDENTIAL_ROTATION=false`, and
     `ENABLE_FIRMWARE_UPDATES=false` during setup and read-only scanning;
   - keep the default ports unless they conflict locally.

3. Validate and start:

   ```bash
   docker compose config --quiet
   docker compose up --build
   ```

4. In another terminal, verify the backend:

   ```bash
   curl --fail --silent http://127.0.0.1:8000/healthz
   ```

5. Open <http://127.0.0.1:3000>. The UI does not scan until the operator clicks
   **Scan Network (read only)** or **Read known IPs**.

Stop the application with `Ctrl-C`, or with `docker compose down` if it was started
detached.

## Checks and local development

Install the exact frontend and Python development dependencies, then run all checks:

```bash
just bootstrap
just check
```

Individual targets are `just lint`, `just format`, `just typecheck`, `just test`,
`just compose-check`, and `just run`.

Without Docker, start the services in separate terminals after `just bootstrap`:

```bash
.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8000
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8000 npm --prefix frontend run dev
```

## Configuration contract

| Setting | Safe default | Contract |
| --- | --- | --- |
| `ALLOWED_SUBNET` | `127.0.0.1/32` | IPv4 CIDR. Every requested scan and write target must be inside it. |
| `MAGEWELL_USERNAME` | empty | Required before any real device report read or write. |
| `MAGEWELL_PASSWORD` | empty | Required before any real device report read or write; never commit it. |
| `MAGEWELL_OLD_PASSWORD` | empty | Temporary rotation input; inject only into the disposable backend process and never store it. |
| `ENABLE_CREDENTIAL_ROTATION` | `false` | Separate lock for one-device-at-a-time password rotation; cannot be enabled with Camera-profile writes. |
| `ENABLE_DEVICE_WRITES` | `false` | Device configuration write boundary for profile settings. Never enable it together with credential rotation. Naming is authorized by its reviewed plan and explicit in-app confirmation. |
| `ENABLE_FIRMWARE_UPDATES` | `false` | Single-device firmware boundary. Camera-profile writes and credential rotation must remain locked. |
| `MAX_SCAN_HOSTS` | `1024` | Maximum hosts in one requested scan; hard ceiling is 4096. |
| `MAX_UPDATE_DEVICES` | `100` | Maximum unique targets in one write request; hard ceiling is 500. |
| `ALLOWED_ORIGINS` | local UI origins | Comma-separated exact browser origins allowed by CORS. |
| `BACKEND_PORT` | `8000` | Host port mapped to FastAPI. |
| `FRONTEND_PORT` | `3000` | Host port mapped to Next.js. |
| `BACKEND_PUBLIC_URL` | `http://127.0.0.1:8000` | Browser-visible backend URL embedded when the frontend image is built. |
| `LOG_LEVEL` | `INFO` | Backend logging level; credentials, cookies, reports, and settings are not logged. |

The Compose ports are intentionally bound to loopback. Use the browser on the operator
workstation; remote UI/API exposure is outside the supported run path. Device scans and
writes also require the UI's `X-Magewell-Operator-Intent: confirmed` header, and browser
requests from origins outside `ALLOWED_ORIGINS` are rejected before device network access.
The header is an intent/CSRF guard, not a secret or a replacement for the write lock.

Embedded-baseline and CSV *settings* writes are disabled. Every supported profile write starts from a
deep-copied settings payload read from an operator-selected live control device. Target-
local identity, management-network, recording-path, and asset-inventory settings are
preserved from each target's successful scan report. The backend rejects schema-mismatched
targets, returns the frozen source SHA-256, and rejects the control source as a target.

## Read versus write behavior

| Operation | Device effect |
| --- | --- |
| `GET /healthz`, `GET /local-subnet` | Local state only; no LAN access. |
| Manual CIDR device scan | Sends read-only ping, login, and report requests inside `ALLOWED_SUBNET`. |
| Known-IP device discovery | Sends the same read-only ping, login, identity, and report requests only to an operator-supplied, de-duplicated list of IPv4 addresses inside `ALLOWED_SUBNET`; invalid, duplicate, or oversized input is rejected before device network access. |
| Select control source | Freezes a deep copy of the already-read live settings and returns its SHA-256; no device write. |
| Profile-plan receipt | Uses only the accepted cached scan and frozen source to show a redacted, ephemeral compatibility/fingerprint plan for the exact selected targets; it opens no device connection, simulates no import, authorizes no write, and is invalidated when inventory, source, target selection, or relevant configuration changes. |
| Durable profile-run receipt | Reads only local durable receipt state. It exposes redacted run identities, fingerprints, mutation/verification status, and an export manifest; it never contacts a device or performs an export. |
| Push selected settings | Reserves and fsyncs one redacted pre-effect receipt before calling Magewell `import-settings` once per explicitly selected, successfully read non-source target. It fails closed before any import if receipt capacity or durable storage is unavailable. |
| Verify target | Performs up to six read-only report checks over a ten-second settle window and compares SHA-256 with that target's expected live-source profile plus preserved target-local settings; no device write or mutation retry. |
| Credential inventory | Authenticates each responder with the new credential first, then the old credential; no device write. |
| Rotate one credential | Uses the authenticated admin `set-passwd` API exactly once, then verifies device identity with the new credential. |
| Firmware preflight | Reads one device's identity, hardware, firmware, settings fingerprint, running state, and stream activity. |
| Update one firmware target | Uploads one exact-hash `.mwf`, starts one install, waits through reboot, and verifies identity and firmware. Neither mutation is retried. |
| CSV baseline update | Rejected; the embedded baseline is not an authorized write source. |
| Naming plan | Builds a reviewed rename plan from the latest successful scan; no device write. |
| Rename batch | Reads and identity-checks each target, submits the authenticated Magewell `set-name` call exactly once, then performs an immediate readback followed by up to five more read-only checks over a ten-second settle window. Only after the display name is visible, if supported recorder-name fields need changes, it submits one `import-settings` call to reset them (`dir-name` becomes `NAME_REC`; `prefix-name` becomes `NAME_`) and uses the same bounded readback window for the final settings. These are two non-atomic device calls; neither mutation is retried. A stop reports the verified versus uncertain stage and submits no later target. |

Profile writes require `ENABLE_DEVICE_WRITES=true`, valid runtime credentials, an explicit UI
confirmation, and a validated non-empty target set. Naming instead requires valid runtime
credentials, a fresh reviewed identity-bound plan, and explicit in-app confirmation; it does
not require restarting the backend to set a development write flag. Only one mutation batch can
run at a time. The mutation call is intentionally not retried, preventing an ambiguous response
from causing a silent second submission. Naming refuses to run while firmware updates or
credential rotation are armed.

The profile-plan receipt is a read-only operator aid, not a write prerequisite. It contains only
source/target identities and deterministic fingerprints, never raw settings, credentials, device
URLs, or cookies. Generate a fresh plan after any source, target, inventory, or configuration
change; an old plan is deliberately not retained or reused by the backend.

## Durable profile-run receipts

Each accepted profile-settings write creates a separate, redacted durable receipt with a fresh
server-side run ID; its accepted input binding is retained separately as a deterministic SHA-256.
Receipts live in the
Compose named volume `magewell_profile_run_receipts`, mounted only in the backend at
`/var/lib/magewell-profile-run-receipts`. It is separate from firmware recovery because firmware
recovery includes a raw settings backup. The backend owns the receipt root and monthly journal
directories at mode `0700`; journal and current-summary files are mode `0600`.

Before the first device import, the backend reserves storage for the pre-effect and terminal
events, appends and fsyncs the intent, then writes bounded mutation and read-back outcomes. A
receipt contains only deterministic identities/fleet metadata, source and target settings hashes,
compatibility and outcome reason codes, bounded verification attempts, and a SHA-256 of each
canonical journal event. It never stores raw settings, credentials, cookies, headers, URLs,
device responses, query strings, or free-form device errors. Until a terminal outcome or
read-back is recorded, the receipt visibly marks the target as `uncertain-high-risk`; do not
retry based on an ambiguous device response.

The monthly append-only JSONL journal is capped at 64 KiB per record and 10 MiB or 10,000
records in total. Receipt data is retained for at least 30 days. Day 30 is a review trigger only:
there is no automatic deletion, no delete API/UI, no individual pruning, and no notification,
automatic backup, or external logging integration.

Use **Inspect local run receipts** in the app to view the redacted current summaries. The local
`GET /profile-run-receipts/export-manifest` endpoint provides the SHA-256, size, and record
count for each journal segment. Export is intentionally manual and outside the repository:

```bash
docker compose cp backend:/var/lib/magewell-profile-run-receipts \
  /private/tmp/magewell-profile-run-receipts
```

Treat every copied receipt as operationally sensitive identity metadata. The copy is a separate
operator-managed artifact and is not automatically retained, synchronized, or deleted by this app.

## Naming devices

Open **Naming** in the local app after a fresh scan. Build one of two reviewable plans:

- **Fleet-journal prefix:** select devices and enter a prefix. Each target's two-digit
  suffix is derived only from the committed `backend/fleet_journal.csv` serial+Ethernet-MAC
  pair, so an IP move cannot renumber it. For example, the device journaled as `AIO-01`
  becomes `ENCODER-01`, while `AIO-13` becomes `ENCODER-13`.
- **CSV mapping:** upload a UTF-8 CSV exported from Excel or Google Sheets with exactly
  `ip,new_name` or `current_name,new_name` headers. Existing-name mappings must resolve
  to exactly one device in the latest scan.

The plan rejects duplicate targets or new names, a CSV name whose suffix does not match the
device's journaled ID, collisions with devices not in the plan, failed scan reports,
unrecognized serial/MAC pairs, out-of-subnet targets, and plans above `MAX_UPDATE_DEVICES`.
Review every IP/current-name/new-name pair and recording-value count. The write button
is available when the plan is ready; the operator's confirmation is the authorization to submit it.
New names must use [Magewell's exact `set-name` contract](https://magewell.com/api-docs/ultra-encode-api/general/set-name.html):
1–32 characters, only letters, numbers, spaces, and `._-+'[](),`, with no leading or trailing
space. On confirmation the backend re-reads every target, checks its serial/MAC identity and
settings fingerprint against the plan, submits `set-name` once, and immediately reads back the
display name before it makes any recorder-settings import. If recorder fields require changes, it then submits one
`import-settings` call and reads back the final full settings. The calls cannot be atomic. Any
failed submission or read-back stops the remaining targets, reports the exact submitted,
not-submitted, and fully verified counts plus the stage that is uncertain, and requires a fresh
scan and fresh plan before any next run. Do not retry the stopped plan; recover or inspect that
one device first.

Credential rotation has a separate `ENABLE_CREDENTIAL_ROTATION` lock and accepts exactly
one target per request. A fresh mixed-credential inventory classifies devices as `old`,
`new`, or `error`. An already-rotated device is verified without another mutation. An
ambiguous password-change response blocks any retry until a fresh inventory determines
which credential works. Camera-profile writes must remain locked throughout rotation.

For a supervised rotation, put the desired final password in `MAGEWELL_PASSWORD`, inject
the old password only as the disposable process environment variable
`MAGEWELL_OLD_PASSWORD`, set `ENABLE_CREDENTIAL_ROTATION=true`, and keep
`ENABLE_DEVICE_WRITES=false`. Run `GET /credential-rotation-inventory` for the exact
approved subnet and require every responder to report `old` or `new`. Submit one explicit
`POST /rotate-credential` target with `confirm: true`; proceed only after
`rotated-and-verified`. Rotate subsequent `old` devices one at a time. Finish with a fresh
inventory in which every device reports `new`, then remove the container. Never retry a
device whose credential state is unknown without first running a fresh inventory.

## Guarded firmware updates

Firmware normalization uses the CLI instead of a bulk browser action. It accepts exactly
one device and requires an exact IP, device name, target version, model/hardware/product
identity, immutable serial/MAC identity, an approved `.mwf` manifest entry, and explicit
`--confirm`. The approved manifest binds version 2.4.288 to Ultra Encode AIO hardware B,
product 787, the manufacturer filename, exact byte size, official package URL, and SHA-256.
The validated file descriptor is the one uploaded. It refuses to run while the device is
streaming, checking/updating firmware, loading settings, resetting, formatting storage, or
rebooting. It also refuses to run if Camera-profile writes or credential rotation are
enabled.

Keep all firmware archives outside the repository. First run the read-only preflight:

```bash
docker compose exec -T backend python -m backend.firmware_cli preflight-one \
  --ip 192.0.2.10 \
  --expected-name ENCODER-01 \
  --target-version 2.4.288
```

For a controlled update, copy the manufacturer `.mwf` into the running backend, set only
`ENABLE_FIRMWARE_UPDATES=true` in `.env`, recreate the backend, and verify `/healthz`
reports firmware enabled with the other two mutation modes disabled. Then invoke:

```bash
docker compose exec -T backend python -m backend.firmware_cli update-one \
  --ip 192.0.2.10 \
  --expected-name ENCODER-01 \
  --expected-serial SERIAL_FROM_PREFLIGHT \
  --expected-eth-mac MAC_FROM_PREFLIGHT \
  --target-version 2.4.288 \
  --firmware /tmp/ultra_encode_aio_gen2_rev_b_2_4_288.mwf \
  --confirm
```

The updater rechecks name, serial, Ethernet MAC, model, hardware, product, firmware, and a
strict idle/non-streaming status in the same authenticated session immediately before upload.
It writes a mode-`0600` settings backup and append-only effect journal below the mode-`0700`
recovery root before uploading. The fixed serial/artifact receipt prevents concurrent or
later duplicate mutation attempts, even from another CLI invocation. Copy the recovery data
off the container after each device; the Compose named volume preserves it across container
recreation:

```bash
docker compose cp backend:/var/lib/magewell-firmware-recovery \
  /private/tmp/magewell-firmware-recovery
```

Magewell warns not to disconnect power or operate the unit during installation; a successful
update reboots automatically. Exact post-reboot identity, credentials, version, idle state,
and settings preservation are verified. Pre-update safety remains strict about Wi-Fi
search/connect activity. Post-reboot verification may report those two background bits after
the firmware is installed, but still requires no streaming, recording, update, reset, loading,
test, occupancy, or reboot activity. The settings comparison ignores only Wi-Fi RSSI and the
exact disabled/default NDI Bridge, ZEN Master, live-keep-last, and PID fields observed when
2.4.288 extends an older schema. Every other changed path returns
`firmware-verified-settings-changed` and stops fleet progression.

If the original invocation stops after an accepted install, relock every effect first. Never
rerun `update-one`. Use the durable receipt for a read-only recovery verification:

```bash
docker compose exec -T backend python -m backend.firmware_cli verify-one \
  --ip 192.0.2.10 \
  --expected-name ENCODER-01 \
  --expected-serial SERIAL_FROM_PREFLIGHT \
  --expected-eth-mac MAC_FROM_PREFLIGHT \
  --target-version 2.4.288
```

If upload/install acceptance is ambiguous, the device does not return within ten minutes, its
identity/version differs, or recovery is uncertain, do not retry. Relock firmware updates and
recover that one device through the manufacturer UI or Magewell support before continuing.
Firmware downgrade is not an assumed recovery path.

If an older firmware update preserves identity/version but resets only
`rec-channels.0.is-use` from the receipt's `1` to `0`, the guarded recovery command can restore
that single value. It refuses any other unexpected drift, creates a durable no-retry receipt,
submits the current settings with only that value repaired, and verifies the full settings
snapshot before fleet progression. Read-only verification waits through the device's temporary
settings-loading state; it never resubmits the repair:

```bash
docker compose exec -T backend python -m backend.firmware_cli restore-recording-one \
  --ip 192.0.2.10 \
  --expected-name ENCODER-01 \
  --expected-serial SERIAL_FROM_PREFLIGHT \
  --expected-eth-mac MAC_FROM_PREFLIGHT \
  --target-version 2.4.288 \
  --confirm
```

## Controlled live-run checklist

Complete this checklist during a supervised bench session:

1. Rotate the previously exposed device credentials and put the new values only in
   the untracked `.env`.
2. Confirm Docker Desktop is running and the workstation is attached only to the intended
   control network.
3. Set the exact approved `ALLOWED_SUBNET`; do not widen or substitute discovery targets.
4. Keep `ENABLE_DEVICE_WRITES=false`; run `just check`,
   `docker compose config --quiet`, and `docker compose up --build -d`.
5. Check `curl --fail --silent http://127.0.0.1:8000/healthz`. Confirm the subnet,
   `device_reads_configured: true`, and `device_writes_enabled: false`.
6. Open the UI and manually scan. Treat the successful live discovery as the inventory;
   stop on any identity mismatch, authentication problem, or read error.
7. Stop the stack, set `ENABLE_DEVICE_WRITES=true`, and recreate it with
   `docker compose up --build -d --force-recreate`. Verify health now reports writes enabled.
8. Rescan, explicitly select the known-good live control source, record its settings
   SHA-256, and select exactly one staged non-source target.
9. Review the displayed source-to-target mapping, submit once, and wait for that target's
   result. Do not proceed on an error or unknown response.
10. Click **Verify Selected Targets (read only)** and confirm every result is `VERIFIED`
    with matching expected and actual SHA-256 values. The app stops verification on the
    first mismatch or read error and keeps the next write locked. Verify the target
    identity, network reachability, and Camera profile directly in the Magewell UI as an
    independent check.
    Only then repeat with the next explicitly reviewed target set. Use **Select all
    targets** for the confirmed remainder or select cards individually; the frozen source
    is always excluded, and **Clear all** resets the batch. Keep each batch within
    `MAX_UPDATE_DEVICES`; never raise the cap silently.
11. At the end, set `ENABLE_DEVICE_WRITES=false`, run
    `docker compose up -d --force-recreate backend`, verify health reports writes locked,
    and run `docker compose down`.

The safest first live action is step 6: a manually initiated read-only scan with writes
locked. The first live effect is step 8/9: one confirmed write to one staged target.

## Recovery and troubleshooting

There is no transactional device rollback. Before the first write, confirm that the
known-good control device or a separately exported manufacturer configuration can be used
for recovery. If a target fails verification, stop the batch, leave writes locked until a
recovery plan is selected, then restore that single device from the known-good control or
the Magewell UI.

- **Cannot connect to Docker:** start Docker Desktop and retry `docker version`.
- **Backend reports credentials missing:** populate both credential variables in `.env`
  and recreate the backend container.
- **Scan is rejected:** make the requested CIDR a subset of `ALLOWED_SUBNET` and keep its
  host count within `MAX_SCAN_HOSTS`.
- **Browser cannot reach the API:** verify `BACKEND_PUBLIC_URL`, `BACKEND_PORT`, and
  `ALLOWED_ORIGINS`, then rebuild the frontend.
- **Writes remain locked:** this is expected until `ENABLE_DEVICE_WRITES=true` is loaded
  into a recreated backend container.
- **HTTP 409 on update:** another batch is running; wait for its per-device results instead
  of submitting again.
