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

interface VerificationResult {
  ip: string;
  magewell_id: string;
  expected_settings_sha256?: string;
  actual_settings_sha256?: string;
  matches_expected_profile: boolean;
  verification_attempts?: number;
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
  const [verificationMessage, setVerificationMessage] = useState("");
  const [verificationResults, setVerificationResults] = useState<
    VerificationResult[]
  >([]);
  const [verificationInProgress, setVerificationInProgress] = useState(false);
  const [verificationRequired, setVerificationRequired] = useState(false);
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
    setVerificationMessage("");
    setVerificationResults([]);
    setVerificationRequired(false);
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
    if (verificationRequired) {
      setPushMessage(
        "Verify the just-written target selection before changing targets.",
      );
      return;
    }
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
      setVerificationMessage("");
      setVerificationResults([]);
      setVerificationRequired(false);
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
      const requiresReadBack = (data.results || []).some(
        (result: UpdateResult) => result.status === "updated",
      );
      setVerificationRequired(requiresReadBack);
      setPushMessage(
        requiresReadBack
          ? "Write response received. Read-back verification is required before another write."
          : "Device update finished without an updated target. Review every result below.",
      );
    } catch (pushError) {
      setPushMessage(
        `Device update failed: ${pushError instanceof Error ? pushError.message : "unknown error"}`,
      );
    } finally {
      setPushInProgress(false);
    }
  };

  const verifySelectedTargets = async () => {
    if (!controlSource) {
      setVerificationMessage(
        "Select and freeze the live control source first.",
      );
      return;
    }
    const selectedDevices = devices.filter((device) =>
      selectedPushIps.includes(device.ip),
    );
    if (selectedDevices.length === 0) {
      setVerificationMessage(
        "Select at least one non-source target to verify.",
      );
      return;
    }

    setVerificationInProgress(true);
    setVerificationMessage("Reading back selected targets...");
    setVerificationResults([]);
    const results: VerificationResult[] = [];
    for (const device of selectedDevices) {
      try {
        const response = await fetch(`${backendBaseUrl}/verify-target`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Magewell-Operator-Intent": "confirmed",
          },
          body: JSON.stringify({
            device: { ip: device.ip, magewell_id: device.name },
          }),
        });
        if (!response.ok) throw new Error(await apiError(response));
        const result: VerificationResult = await response.json();
        results.push(result);
        setVerificationResults([...results]);
        if (!result.matches_expected_profile) break;
      } catch (verificationError) {
        results.push({
          ip: device.ip,
          magewell_id: device.name,
          matches_expected_profile: false,
          error:
            verificationError instanceof Error
              ? verificationError.message
              : "unknown verification error",
        });
        setVerificationResults([...results]);
        break;
      }
    }

    const allVerified =
      results.length === selectedDevices.length &&
      results.every((result) => result.matches_expected_profile);
    if (allVerified) {
      setVerificationRequired(false);
      setSelectedPushIps([]);
      setVerificationMessage(
        `Read-back verified ${results.length} target${results.length === 1 ? "" : "s"}; the next target selection is unlocked.`,
      );
    } else {
      setVerificationRequired(true);
      setVerificationMessage(
        "Read-back stopped on the first mismatch or error. Keep writes stopped and investigate before retrying.",
      );
    }
    setVerificationInProgress(false);
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
            verificationInProgress ||
            verificationRequired ||
            !writesEnabled ||
            !controlSource ||
            selectedPushIps.length === 0
          }
        >
          {pushInProgress
            ? "Updating..."
            : "Write Settings to Selected Devices"}
        </button>
        <button
          onClick={verifySelectedTargets}
          className={styles.button28}
          disabled={
            pushInProgress ||
            verificationInProgress ||
            !controlSource ||
            selectedPushIps.length === 0
          }
        >
          {verificationInProgress
            ? "Verifying..."
            : "Verify Selected Targets (read only)"}
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
        {verificationMessage && (
          <p className={styles.pushResult}>{verificationMessage}</p>
        )}
        {verificationResults.length > 0 && (
          <ul className={styles.selectedList}>
            {verificationResults.map((result) => (
              <li key={result.ip}>
                {result.magewell_id} — {result.ip}:{" "}
                {result.matches_expected_profile ? "VERIFIED" : "STOP"}
                {result.verification_attempts
                  ? ` after ${result.verification_attempts} read${result.verification_attempts === 1 ? "" : "s"}`
                  : ""}
                {result.error ? ` (${result.error})` : ""}
                {result.expected_settings_sha256
                  ? ` — expected ${result.expected_settings_sha256}`
                  : ""}
                {result.actual_settings_sha256
                  ? ` — actual ${result.actual_settings_sha256}`
                  : ""}
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
