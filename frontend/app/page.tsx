"use client";

import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import DeviceGrid from "@/components/DeviceGrid";
import { Device } from "@/components/DeviceCard";
import WaterfallIcon from "@/components/Waterfall";
import styles from "./page.module.css";

const backendBaseUrl = (
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");

interface UpdateResult {
  ip: string;
  magewell_id: string;
  status: string;
  error?: string;
}

interface ControlSource {
  ip: string;
  magewell_id: string;
  settings_sha256: string;
}

async function apiError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body.detail || body.error || response.statusText;
  } catch {
    return response.statusText;
  }
}

export default function HomePage() {
  const [loading, setLoading] = useState(false);
  const [devices, setDevices] = useState<Device[]>([]);
  const [error, setError] = useState("");
  const [subnet, setSubnet] = useState("");
  const [selectedControlDevice, setSelectedControlDevice] =
    useState<Device | null>(null);
  const [selectedPushIps, setSelectedPushIps] = useState<string[]>([]);
  const [controlMessage, setControlMessage] = useState("");
  const [controlSource, setControlSource] = useState<ControlSource | null>(
    null,
  );
  const [pushMessage, setPushMessage] = useState("");
  const [pushResults, setPushResults] = useState<UpdateResult[]>([]);
  const [pushInProgress, setPushInProgress] = useState(false);
  const [writesEnabled, setWritesEnabled] = useState(false);

  useEffect(() => {
    const loadSafeStatus = async () => {
      try {
        const [subnetResponse, healthResponse] = await Promise.all([
          fetch(`${backendBaseUrl}/local-subnet`),
          fetch(`${backendBaseUrl}/healthz`),
        ]);
        if (!subnetResponse.ok || !healthResponse.ok) {
          throw new Error("Backend status check failed.");
        }
        const subnetData = await subnetResponse.json();
        const healthData = await healthResponse.json();
        setSubnet(subnetData.local_subnet || "");
        setWritesEnabled(Boolean(healthData.device_writes_enabled));
      } catch (statusError) {
        console.error("Backend status check failed:", statusError);
        setError("Backend is unavailable. Start it, then reload this page.");
      }
    };
    void loadSafeStatus();
  }, []);

  const scanNetwork = async (subnetToScan: string, forceRescan = false) => {
    if (!subnetToScan) return;
    setLoading(true);
    setError("");
    setDevices([]);
    setSelectedPushIps([]);
    setPushResults([]);
    try {
      const url = `${backendBaseUrl}/discover-magewell?subnet=${encodeURIComponent(
        subnetToScan,
      )}&per_ip_timeout=1.0&max_concurrent=50&rescan=${forceRescan}`;
      const response = await fetch(url, {
        headers: { "X-Magewell-Operator-Intent": "confirmed" },
      });
      if (!response.ok) throw new Error(await apiError(response));
      const data = await response.json();
      setDevices(data.devices || []);
    } catch (scanError) {
      setError(
        scanError instanceof Error ? scanError.message : "Network scan failed.",
      );
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setControlMessage("");
    setControlSource(null);
    setSelectedControlDevice(null);
    setPushMessage("");
    void scanNetwork(subnet, true);
  };

  const handleSelectToggle = (device: Device) => {
    if (device.ip === controlSource?.ip) {
      setPushMessage(
        "The frozen control source cannot be selected as a write target.",
      );
      return;
    }
    setSelectedPushIps((previous) =>
      previous.includes(device.ip)
        ? previous.filter((ip) => ip !== device.ip)
        : [...previous, device.ip],
    );
  };

  const handleConfirmControl = async () => {
    if (!selectedControlDevice) return;
    try {
      const response = await fetch(`${backendBaseUrl}/set-control`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ip: selectedControlDevice.ip,
          magewell_id: selectedControlDevice.name,
        }),
      });
      if (!response.ok) throw new Error(await apiError(response));
      const data: ControlSource = await response.json();
      setControlSource(data);
      setSelectedPushIps((previous) =>
        previous.filter((ip) => ip !== selectedControlDevice.ip),
      );
      setControlMessage(
        `Frozen live source ${data.magewell_id} (${data.ip}); settings SHA-256 ${data.settings_sha256}.`,
      );
    } catch (controlError) {
      setControlMessage(
        `Control selection failed: ${
          controlError instanceof Error ? controlError.message : "unknown error"
        }`,
      );
    } finally {
      setSelectedControlDevice(null);
    }
  };

  const pushUpdates = async () => {
    if (!writesEnabled) {
      setPushMessage("Device writes are locked by the backend configuration.");
      return;
    }
    if (selectedPushIps.length === 0) {
      setPushMessage("Select at least one device.");
      return;
    }
    if (!controlSource) {
      setPushMessage("Select and freeze the live control source first.");
      return;
    }
    const confirmed = window.confirm(
      `Write frozen source ${controlSource.magewell_id} (${controlSource.ip}, SHA-256 ${controlSource.settings_sha256}) to exactly ${selectedPushIps.length} selected non-source device(s)? This changes device configuration.`,
    );
    if (!confirmed) {
      setPushMessage("Update cancelled; no write request was sent.");
      return;
    }

    const devicesToUpdate = devices
      .filter((device) => selectedPushIps.includes(device.ip))
      .map((device) => ({ ip: device.ip, magewell_id: device.name }));
    setPushInProgress(true);
    setPushMessage("Updating selected devices...");
    setPushResults([]);
    try {
      const response = await fetch(`${backendBaseUrl}/push-updates`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Magewell-Operator-Intent": "confirmed",
        },
        body: JSON.stringify({ devices: devicesToUpdate, confirm: true }),
      });
      if (!response.ok) throw new Error(await apiError(response));
      const data = await response.json();
      setPushResults(data.results || []);
      setPushMessage("Device update finished. Review every result below.");
    } catch (pushError) {
      setPushMessage(
        `Device update failed: ${pushError instanceof Error ? pushError.message : "unknown error"}`,
      );
    } finally {
      setPushInProgress(false);
    }
  };

  return (
    <div className={styles.main}>
      <div className={styles.formWrapper}>
        <form onSubmit={handleSubmit}>
          <label htmlFor="subnet" className={styles.label}>
            Subnet to scan:
          </label>
          <input
            id="subnet"
            type="text"
            value={subnet}
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              setSubnet(event.target.value)
            }
            className={styles.input}
            placeholder="Enter an allowed CIDR"
          />
          <button type="submit" className={styles.button28} disabled={loading}>
            {loading ? "Scanning..." : "Scan Network (read only)"}
          </button>
        </form>
      </div>

      <div className={styles.messageWrapper}>
        <p className={styles.count}>
          Device writes:{" "}
          {writesEnabled ? "ENABLED — use controlled-run procedure" : "LOCKED"}
        </p>
        <p className={styles.count}>
          Found {devices.length} device{devices.length === 1 ? "" : "s"}.
        </p>
        {controlMessage && (
          <div className={styles.controlMessage}>{controlMessage}</div>
        )}
      </div>

      <div className={styles.gridWrapper}>
        {loading ? (
          <>
            <p className={styles.count}>Scanning...</p>
            <WaterfallIcon />
          </>
        ) : devices.length > 0 ? (
          <DeviceGrid
            devices={devices}
            selectedDeviceIps={selectedPushIps}
            onSelectToggle={handleSelectToggle}
            onSetControl={setSelectedControlDevice}
          />
        ) : (
          <p className={styles.count}>
            No scan results. Scans start only when you click the button.
          </p>
        )}
      </div>

      {error && <p className={styles.count}>Error: {error}</p>}

      <div className={styles.pushContainer}>
        <h2>Frozen live source</h2>
        <p>
          {controlSource
            ? `${controlSource.magewell_id} — ${controlSource.ip} — ${controlSource.settings_sha256}`
            : "None selected. The embedded baseline is disabled."}
        </p>
        <h2>Selected write targets: {selectedPushIps.length}</h2>
        {selectedPushIps.length > 0 && (
          <ul className={styles.selectedList}>
            {selectedPushIps.map((ip) => {
              const device = devices.find((candidate) => candidate.ip === ip);
              return (
                <li key={ip}>
                  {device?.name || "Unnamed device"} — {ip}
                </li>
              );
            })}
          </ul>
        )}
        <button
          onClick={pushUpdates}
          className={styles.button28}
          disabled={
            pushInProgress ||
            !writesEnabled ||
            !controlSource ||
            selectedPushIps.length === 0
          }
        >
          {pushInProgress
            ? "Updating..."
            : "Write Settings to Selected Devices"}
        </button>
        {pushMessage && <p className={styles.pushResult}>{pushMessage}</p>}
        {pushResults.length > 0 && (
          <ul className={styles.selectedList}>
            {pushResults.map((result) => (
              <li key={result.ip}>
                {result.magewell_id} — {result.ip}: {result.status}
                {result.error ? ` (${result.error})` : ""}
              </li>
            ))}
          </ul>
        )}
      </div>

      {selectedControlDevice && (
        <div
          className={styles.modalOverlay}
          onClick={() => setSelectedControlDevice(null)}
        >
          <div
            className={styles.modal}
            onClick={(event) => event.stopPropagation()}
          >
            <h2>Select Read-Only Control Source</h2>
            <p>
              Use{" "}
              <strong>{selectedControlDevice.name || "Unnamed Device"}</strong>{" "}
              ({selectedControlDevice.ip}) as the settings source?
            </p>
            <div className={styles.modalButtons}>
              <button
                onClick={() => setSelectedControlDevice(null)}
                className={styles.button28}
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmControl}
                className={styles.button28}
              >
                Confirm Source
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
