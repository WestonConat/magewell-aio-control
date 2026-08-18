# Magewell AIO Control

Magewell AIO Control is a local Next.js and FastAPI utility for discovering Magewell
Ultra Encode AIO devices, reading one device as a control-settings source, and applying
settings to explicitly selected targets. It is intended for a supervised local-network
maintenance window, not as an unattended fleet service.

The application is safe by default: it uses a loopback-only subnet, never scans on page
load, and rejects every device-write request unless the operator explicitly enables the
write boundary and confirms the target set.

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
   - keep `ENABLE_DEVICE_WRITES=false` during setup and read-only scanning;
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
   **Scan Network (read only)**.

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
| `ENABLE_DEVICE_WRITES` | `false` | The single real-device effect boundary. Only `true` unlocks write endpoints. |
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

CSV baseline updates accept UTF-8 `.csv` files with exactly these required columns:

```csv
Magewell ID,Magewell IP
ENCODER-01,192.0.2.10
```

See `backend/devices.example.csv`. IPs must be unique and inside `ALLOWED_SUBNET`;
blank IDs, malformed files, duplicate IPs, and excessive row counts are rejected before
network access.

## Read versus write behavior

| Operation | Device effect |
| --- | --- |
| `GET /healthz`, `GET /local-subnet` | Local state only; no LAN access. |
| Manual device scan | Sends read-only ping, login, and report requests inside `ALLOWED_SUBNET`. |
| Select control source | Stores the already-read settings in backend memory; no device write. |
| Push selected settings | Calls Magewell `import-settings` once per explicitly selected, scanned target. |
| CSV baseline update | Calls `import-settings` once per validated CSV row using the embedded baseline. |

Writes require all of the following: `ENABLE_DEVICE_WRITES=true`, valid runtime
credentials, an explicit UI confirmation, and a validated non-empty target set. Only one
write batch can run at a time. The mutation call is intentionally not retried, preventing
an ambiguous response from causing a silent second submission. The UI reports success or
failure for every target.

## Controlled live-run checklist

Complete this checklist during the maintenance window:

1. Rotate the previously exposed device credentials and put the new values only in
   the untracked `.env`.
2. Confirm Docker Desktop is running and the workstation is attached only to the intended
   control network.
3. Set the smallest correct `ALLOWED_SUBNET`; verify the intended device IPs and CSV rows
   are inside it.
4. Keep `ENABLE_DEVICE_WRITES=false`; run `just check`,
   `docker compose config --quiet`, and `docker compose up --build -d`.
5. Check `curl --fail --silent http://127.0.0.1:8000/healthz`. Confirm the subnet,
   `device_reads_configured: true`, and `device_writes_enabled: false`.
6. Open the UI and manually scan. Reconcile the discovered names/IPs against the run sheet.
   Stop if any unexpected device or read error appears.
7. Stop the stack, set `ENABLE_DEVICE_WRITES=true`, and recreate it with
   `docker compose up --build -d --force-recreate`. Verify health now reports writes enabled.
8. Rescan, select the known-good control source, and select exactly one staged test target.
9. Review the confirmation count, submit once, and wait for that target's result. Do not
   proceed on an error or unknown response.
10. Verify the staged target directly in the Magewell UI. Only then repeat with the next
    small, explicitly reviewed target set.
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
