"use client";

import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";
import styles from "../page.module.css";

const backendBaseUrl = (
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");

type Device = {
  ip: string;
  name: string;
  fleet_id?: string;
  serial?: string;
  eth_mac?: string;
  identity_error?: string;
  name_journal_mismatch?: boolean;
};
type Mapping = { ip?: string; current_name?: string; new_name: string };
type RenameTarget = {
  ip: string;
  fleet_id: string;
  serial: string;
  eth_mac: string;
  current_name: string;
  new_name: string;
  recording_changes: Array<{ path: string; before: string; after: string }>;
};
type RenamePlan = { plan_id: string; targets: RenameTarget[] };
type Result = RenameTarget & { status: string; error?: string };

async function apiError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body.detail || response.statusText;
  } catch {
    return response.statusText;
  }
}

function parseCsv(text: string): Mapping[] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (character === '"') {
      if (quoted && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else quoted = !quoted;
    } else if (character === "," && !quoted) {
      row.push(field.trim());
      field = "";
    } else if ((character === "\n" || character === "\r") && !quoted) {
      if (character === "\r" && text[index + 1] === "\n") index += 1;
      row.push(field.trim());
      if (row.some(Boolean)) rows.push(row);
      row = [];
      field = "";
    } else field += character;
  }
  row.push(field.trim());
  if (row.some(Boolean)) rows.push(row);
  if (quoted || rows.length < 2)
    throw new Error("CSV needs a header and at least one mapping row.");
  const headers = rows[0].map((value) =>
    value.toLowerCase().replaceAll(" ", "_"),
  );
  const ipIndex = headers.indexOf("ip");
  const currentIndex = Math.max(
    headers.indexOf("current_name"),
    headers.indexOf("existing_name"),
  );
  const newIndex = headers.indexOf("new_name");
  if (
    newIndex < 0 ||
    (ipIndex < 0 && currentIndex < 0) ||
    (ipIndex >= 0 && currentIndex >= 0)
  ) {
    throw new Error(
      "CSV headers must be ip,new_name or current_name,new_name.",
    );
  }
  return rows.slice(1).map((values, index) => {
    const newName = values[newIndex] || "";
    if (!newName) throw new Error(`Row ${index + 2} has no new_name.`);
    return ipIndex >= 0
      ? { ip: values[ipIndex], new_name: newName }
      : { current_name: values[currentIndex], new_name: newName };
  });
}

export default function NamingPage() {
  const [subnet, setSubnet] = useState("");
  const [devices, setDevices] = useState<Device[]>([]);
  const [mode, setMode] = useState<"prefix" | "csv">("prefix");
  const [prefix, setPrefix] = useState("ENCODER");
  const [selectedIps, setSelectedIps] = useState<string[]>([]);
  const [mappings, setMappings] = useState<Mapping[]>([]);
  const [plan, setPlan] = useState<RenamePlan | null>(null);
  const [results, setResults] = useState<Result[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [writesEnabled, setWritesEnabled] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const [subnetResponse, healthResponse] = await Promise.all([
          fetch(`${backendBaseUrl}/local-subnet`),
          fetch(`${backendBaseUrl}/healthz`),
        ]);
        if (!subnetResponse.ok || !healthResponse.ok)
          throw new Error("Backend is unavailable.");
        setSubnet((await subnetResponse.json()).local_subnet || "");
        setWritesEnabled(
          Boolean((await healthResponse.json()).device_writes_enabled),
        );
      } catch (error) {
        setMessage(
          error instanceof Error ? error.message : "Backend is unavailable.",
        );
      }
    })();
  }, []);

  const sortedDevices = useMemo(
    () =>
      [...devices].sort((left, right) =>
        (left.fleet_id || "ZZZ").localeCompare(right.fleet_id || "ZZZ"),
      ),
    [devices],
  );

  const scan = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setMessage("");
    setPlan(null);
    setResults([]);
    try {
      const response = await fetch(
        `${backendBaseUrl}/discover-magewell?subnet=${encodeURIComponent(subnet)}&per_ip_timeout=3&max_concurrent=20&settings_timeout=5&rescan=true`,
        { headers: { "X-Magewell-Operator-Intent": "confirmed" } },
      );
      if (!response.ok) throw new Error(await apiError(response));
      const found = (await response.json()).devices || [];
      setDevices(found);
      const journaled = found.filter((device: Device) => device.fleet_id);
      setSelectedIps(journaled.map((device: Device) => device.ip));
      setMessage(
        `${found.length} devices read; ${journaled.length} match the immutable fleet journal. Review a rename plan before any write.`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Scan failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const rows = parseCsv(await file.text());
      setMappings(rows);
      setPlan(null);
      setMessage(
        `${rows.length} CSV mappings loaded. Build the plan to validate against the latest scan.`,
      );
    } catch (error) {
      setMappings([]);
      setMessage(
        error instanceof Error ? error.message : "CSV could not be read.",
      );
    }
  };

  const buildPlan = async () => {
    setLoading(true);
    setMessage("");
    setResults([]);
    try {
      const body =
        mode === "csv" ? { mappings } : { prefix, device_ips: selectedIps };
      const response = await fetch(`${backendBaseUrl}/rename-plan`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Magewell-Operator-Intent": "confirmed",
        },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(await apiError(response));
      setPlan(await response.json());
      setMessage("Plan frozen from the latest scan. Nothing has been written.");
    } catch (error) {
      setPlan(null);
      setMessage(
        error instanceof Error ? error.message : "Plan could not be built.",
      );
    } finally {
      setLoading(false);
    }
  };

  const execute = async () => {
    if (!plan || !writesEnabled) return;
    if (
      !window.confirm(
        `Rename exactly ${plan.targets.length} device(s), update their matching recording values, and verify each device before proceeding?`,
      )
    )
      return;
    setLoading(true);
    setMessage("Submitting sequential rename plan…");
    try {
      const response = await fetch(`${backendBaseUrl}/rename-execute`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Magewell-Operator-Intent": "confirmed",
        },
        body: JSON.stringify({ plan_id: plan.plan_id, confirm: true }),
      });
      if (!response.ok) throw new Error(await apiError(response));
      const data = await response.json();
      setResults(data.results || []);
      setMessage(
        "Rename run finished. Do not retry a stopped plan; scan and build a fresh plan.",
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Rename run failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className={styles.main}>
      <div className={styles.topBar}>
        <h1>Naming</h1>
        <span
          className={`${styles.writeStatus} ${writesEnabled ? styles.statusArmed : styles.statusLocked}`}
        >
          {writesEnabled ? "WRITES ARMED" : "WRITES LOCKED"}
        </span>
      </div>
      <form className={styles.scanPanel} onSubmit={scan}>
        <div className={styles.fieldGroup}>
          <label className={styles.label} htmlFor="subnet">
            Allowed subnet
          </label>
          <input
            id="subnet"
            className={styles.input}
            value={subnet}
            onChange={(event) => setSubnet(event.target.value)}
            required
          />
        </div>
        <button
          className={styles.primaryButton}
          disabled={loading}
          type="submit"
        >
          {loading ? "Working…" : "Scan devices"}
        </button>
        <div className={styles.inventoryCount}>
          {devices.length ? `${devices.length} scanned` : "No inventory"}
        </div>
      </form>
      <section className={styles.workflowPanel}>
        <div className={styles.sectionHeading}>
          <h2>Build rename plan</h2>
          <div className={styles.bulkActions}>
            <button
              type="button"
              className={
                mode === "prefix"
                  ? styles.primaryButton
                  : styles.secondaryButton
              }
              onClick={() => {
                setMode("prefix");
                setPlan(null);
              }}
            >
              Fleet journal
            </button>
            <button
              type="button"
              className={
                mode === "csv" ? styles.primaryButton : styles.secondaryButton
              }
              onClick={() => {
                setMode("csv");
                setPlan(null);
              }}
            >
              CSV mapping
            </button>
          </div>
        </div>
        {mode === "prefix" ? (
          <>
            <div className={styles.namingFields}>
              <div className={styles.fieldGroup}>
                <label className={styles.label}>Prefix</label>
                <input
                  className={styles.input}
                  value={prefix}
                  onChange={(event) => setPrefix(event.target.value)}
                />
              </div>
            </div>
            <p className={styles.mutedCopy}>
              The fleet journal locks the suffix to serial + MAC:{" "}
              {prefix || "PREFIX"}_01, {prefix || "PREFIX"}_02, and so on. IP
              address never determines a device number.
            </p>
            <div className={styles.bulkActions}>
              <button
                type="button"
                className={styles.textButton}
                onClick={() =>
                  setSelectedIps(
                    devices
                      .filter((device) => device.fleet_id)
                      .map((device) => device.ip),
                  )
                }
              >
                Select all
              </button>
              <button
                type="button"
                className={styles.textButton}
                onClick={() => setSelectedIps([])}
              >
                Clear all
              </button>
            </div>
            <div className={styles.namingDeviceList}>
              {sortedDevices.map((device) => (
                <label key={device.ip} className={styles.namingDevice}>
                  <input
                    type="checkbox"
                    checked={selectedIps.includes(device.ip)}
                    disabled={!device.fleet_id}
                    onChange={() => {
                      setPlan(null);
                      setSelectedIps((current) =>
                        current.includes(device.ip)
                          ? current.filter((ip) => ip !== device.ip)
                          : [...current, device.ip],
                      );
                    }}
                  />
                  <span>
                    {device.name || "Unnamed"}
                    {device.fleet_id
                      ? ` · ${device.fleet_id}`
                      : " · journal mismatch"}
                    {device.name_journal_mismatch ? " · suffix mismatch" : ""}
                  </span>
                  <small>
                    {device.ip}
                    {device.identity_error ? ` · ${device.identity_error}` : ""}
                    {device.identity_error && device.serial && device.eth_mac
                      ? ` · ${device.serial} / ${device.eth_mac}`
                      : ""}
                  </small>
                </label>
              ))}
            </div>
          </>
        ) : (
          <>
            <div className={styles.fileRow}>
              <input type="file" accept=".csv,text/csv" onChange={handleFile} />
              <span className={styles.mutedCopy}>
                Headers: <code>ip,new_name</code> or{" "}
                <code>current_name,new_name</code>. Export Excel/Sheets as CSV.
              </span>
            </div>
            <p className={styles.mutedCopy}>
              {mappings.length
                ? `${mappings.length} mappings loaded.`
                : "No mapping file loaded."}
            </p>
          </>
        )}
        <div className={styles.actionRow}>
          <button
            type="button"
            className={styles.primaryButton}
            disabled={
              loading ||
              devices.length === 0 ||
              (mode === "csv" && mappings.length === 0)
            }
            onClick={buildPlan}
          >
            Build review plan
          </button>
        </div>
      </section>
      {message && <div className={styles.notice}>{message}</div>}
      {plan && (
        <section className={styles.encodersSection}>
          <div className={styles.sectionHeading}>
            <h2>Review {plan.targets.length} changes</h2>
            <button
              type="button"
              className={styles.primaryButton}
              disabled={loading || !writesEnabled}
              onClick={execute}
            >
              {writesEnabled ? "Confirm and rename" : "Writes locked"}
            </button>
          </div>
          <div className={styles.renameRows}>
            {plan.targets.map((target) => (
              <div className={styles.renameRow} key={target.ip}>
                <span>
                  <strong>{target.current_name}</strong>
                  <small>
                    {target.ip} · {target.fleet_id}
                  </small>
                </span>
                <b>→</b>
                <span>
                  <strong>{target.new_name}</strong>
                  <small>
                    {target.recording_changes.length
                      ? `${target.recording_changes.length} recording value(s) updated`
                      : "No recording value contains current name"}
                  </small>
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
      {results.length > 0 && (
        <section className={styles.encodersSection}>
          <h2>Run result</h2>
          <div className={styles.renameRows}>
            {results.map((result) => (
              <div className={styles.renameRow} key={result.ip}>
                <span>
                  <strong>{result.ip}</strong>
                  <small>
                    {result.current_name} → {result.new_name}
                  </small>
                </span>
                <span
                  className={
                    result.status === "renamed-and-verified"
                      ? styles.resultVerified
                      : styles.resultStopped
                  }
                >
                  {result.status}
                  {result.error ? ` · ${result.error}` : ""}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
