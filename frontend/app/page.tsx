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

function shortHash(value?: string): string {
  if (!value) return "Unavailable";
  return `${value.slice(0, 8)}…${value.slice(-8)}`;
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
  const eligibleTargetIps = devices
    .filter((device) => device.ip !== controlSource?.ip)
    .map((device) => device.ip);
  const allTargetsSelected =
    eligibleTargetIps.length > 0 &&
    eligibleTargetIps.every((ip) => selectedPushIps.includes(ip));
  const selectedDevices = devices.filter((device) =>
    selectedPushIps.includes(device.ip),
  );

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

  const handleSelectAll = () => {
    if (verificationRequired) {
      setPushMessage(
        "Verify the just-written target selection before changing targets.",
      );
      return;
    }
    setSelectedPushIps(eligibleTargetIps);
    setPushMessage("");
  };

  const handleClearAll = () => {
    if (verificationRequired) {
      setPushMessage(
        "Verify the just-written target selection before changing targets.",
      );
      return;
    }
    setSelectedPushIps([]);
    setPushMessage("");
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
        `Source frozen: ${data.magewell_id} (${data.ip}) · Profile ${shortHash(data.settings_sha256)}`,
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
      `Write profile ${shortHash(controlSource.settings_sha256)} from ${controlSource.magewell_id} (${controlSource.ip}) to exactly ${selectedPushIps.length} selected non-source device(s)? This changes device configuration.`,
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
    <main className={styles.main}>
      <section className={styles.hero}>
        <div>
          <p className={styles.eyebrow}>Bench control</p>
          <h1>Encoder fleet</h1>
          <p className={styles.heroCopy}>
            Discover devices, choose one live source, then push and verify a
            reviewed target set.
          </p>
        </div>
        <span
          className={`${styles.statusPill} ${
            writesEnabled ? styles.statusArmed : styles.statusLocked
          }`}
        >
          <span className={styles.statusDot} />
          Writes {writesEnabled ? "enabled" : "locked"}
        </span>
      </section>

      <section className={styles.scanPanel}>
        <form onSubmit={handleSubmit} className={styles.scanForm}>
          <div className={styles.fieldGroup}>
            <label htmlFor="subnet" className={styles.label}>
              Discovery subnet
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
          </div>
          <button
            type="submit"
            className={styles.primaryButton}
            disabled={loading}
          >
            {loading ? "Scanning…" : "Scan network"}
          </button>
        </form>
        <div className={styles.scanMeta}>
          <div>
            <span>Mode</span>
            <strong>Read only</strong>
          </div>
          <div>
            <span>Inventory</span>
            <strong>
              {loading
                ? "Scanning…"
                : `${devices.length} encoder${devices.length === 1 ? "" : "s"}`}
            </strong>
          </div>
        </div>
        {controlMessage && <p className={styles.notice}>{controlMessage}</p>}
        {error && <p className={styles.errorNotice}>{error}</p>}
      </section>

      {loading ? (
        <section className={styles.loadingState}>
          <WaterfallIcon />
          <p>Reading the approved subnet…</p>
        </section>
      ) : devices.length > 0 ? (
        <>
          <section className={styles.workflowPanel}>
            <div className={styles.sectionHeading}>
              <div>
                <p className={styles.eyebrow}>Current batch</p>
                <h2>Source and targets</h2>
              </div>
              {verificationRequired && (
                <span className={styles.verifyBadge}>
                  Verification required
                </span>
              )}
            </div>

            <div className={styles.workflowGrid}>
              <div className={styles.summaryCard}>
                <span className={styles.summaryLabel}>Live source</span>
                <strong>
                  {controlSource?.magewell_id || "Choose an encoder below"}
                </strong>
                <span className={styles.summaryMeta}>
                  {controlSource
                    ? `${controlSource.ip} · Profile ${shortHash(
                        controlSource.settings_sha256,
                      )}`
                    : "Embedded baselines are disabled"}
                </span>
              </div>
              <div className={styles.summaryCard}>
                <span className={styles.summaryLabel}>Write targets</span>
                <strong>
                  {selectedPushIps.length} selected
                  {eligibleTargetIps.length > 0
                    ? ` of ${eligibleTargetIps.length}`
                    : ""}
                </strong>
                <span className={styles.summaryMeta}>
                  {selectedPushIps.length > 0
                    ? selectedDevices
                        .slice(0, 3)
                        .map((device) => device.name)
                        .join(", ") +
                      (selectedDevices.length > 3
                        ? ` +${selectedDevices.length - 3} more`
                        : "")
                    : "No target devices selected"}
                </span>
              </div>
            </div>

            <div className={styles.actionRow}>
              <button
                onClick={pushUpdates}
                className={styles.primaryButton}
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
                  ? "Writing…"
                  : `Write to ${selectedPushIps.length || 0} target${
                      selectedPushIps.length === 1 ? "" : "s"
                    }`}
              </button>
              <button
                onClick={verifySelectedTargets}
                className={styles.secondaryButton}
                disabled={
                  pushInProgress ||
                  verificationInProgress ||
                  !controlSource ||
                  selectedPushIps.length === 0
                }
              >
                {verificationInProgress ? "Verifying…" : "Verify read-back"}
              </button>
            </div>

            {(pushMessage || verificationMessage) && (
              <div className={styles.resultMessages}>
                {pushMessage && <p>{pushMessage}</p>}
                {verificationMessage && <p>{verificationMessage}</p>}
              </div>
            )}
            {(pushResults.length > 0 || verificationResults.length > 0) && (
              <div className={styles.resultsList}>
                {pushResults.map((result) => (
                  <div className={styles.resultRow} key={`push-${result.ip}`}>
                    <span>
                      <strong>{result.magewell_id}</strong>
                      <small>{result.ip}</small>
                    </span>
                    <span className={styles.resultStatus}>{result.status}</span>
                    {result.error && <small>{result.error}</small>}
                  </div>
                ))}
                {verificationResults.map((result) => (
                  <div className={styles.resultRow} key={`verify-${result.ip}`}>
                    <span>
                      <strong>{result.magewell_id}</strong>
                      <small>{result.ip}</small>
                    </span>
                    <span
                      className={
                        result.matches_expected_profile
                          ? styles.resultVerified
                          : styles.resultStopped
                      }
                    >
                      {result.matches_expected_profile ? "Verified" : "Stop"}
                    </span>
                    <small>
                      {result.error
                        ? result.error
                        : result.matches_expected_profile
                          ? `Profile ${shortHash(result.actual_settings_sha256)} · ${
                              result.verification_attempts || 1
                            } read${
                              result.verification_attempts === 1 ? "" : "s"
                            }`
                          : `Expected ${shortHash(
                              result.expected_settings_sha256,
                            )} · got ${shortHash(
                              result.actual_settings_sha256,
                            )}`}
                    </small>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className={styles.encodersSection}>
            <div className={styles.sectionHeading}>
              <div>
                <p className={styles.eyebrow}>Inventory</p>
                <h2>{devices.length} encoders</h2>
              </div>
              <div className={styles.bulkActions}>
                <button
                  className={styles.textButton}
                  onClick={handleSelectAll}
                  disabled={
                    verificationRequired ||
                    eligibleTargetIps.length === 0 ||
                    allTargetsSelected
                  }
                >
                  Select all targets
                </button>
                <button
                  className={styles.textButton}
                  onClick={handleClearAll}
                  disabled={
                    verificationRequired || selectedPushIps.length === 0
                  }
                >
                  Clear all
                </button>
              </div>
            </div>
            <DeviceGrid
              devices={devices}
              selectedDeviceIps={selectedPushIps}
              controlSourceIp={controlSource?.ip}
              onSelectToggle={handleSelectToggle}
              onSetControl={setSelectedControlDevice}
            />
          </section>
        </>
      ) : (
        <section className={styles.emptyState}>
          <p className={styles.eyebrow}>No inventory yet</p>
          <h2>Start with a read-only scan</h2>
          <p>The app never scans until you click the button.</p>
        </section>
      )}

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
                className={styles.secondaryButton}
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmControl}
                className={styles.primaryButton}
              >
                Confirm Source
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
