"use client";

import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import DeviceGrid from "@/components/DeviceGrid";
import { Device } from "@/components/DeviceCard";
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
  compatible_target_ips: string[];
  incompatible_targets: Array<{ ip: string; reason: string }>;
}

interface ProfilePlanTarget {
  ip: string;
  magewell_id: string;
  serial: string;
  eth_mac: string;
  fleet_id?: string | null;
  current_settings_sha256: string;
  profile_compatible: boolean;
  compatibility_reason?: string;
  expected_settings_sha256?: string;
}

interface ProfilePlan {
  plan_id: string;
  inventory_sha256: string;
  source: {
    ip: string;
    magewell_id: string;
    serial: string;
    eth_mac: string;
    fleet_id?: string | null;
    settings_sha256: string;
  };
  targets: ProfilePlanTarget[];
  all_targets_profile_compatible: boolean;
  mode: "read-only-compatibility-plan";
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
  const [scanMode, setScanMode] = useState<"subnet" | "known-ips">("subnet");
  const [knownIps, setKnownIps] = useState("");
  const [selectedControlDevice, setSelectedControlDevice] =
    useState<Device | null>(null);
  const [selectedPushIps, setSelectedPushIps] = useState<string[]>([]);
  const [controlMessage, setControlMessage] = useState("");
  const [controlSource, setControlSource] = useState<ControlSource | null>(
    null,
  );
  const [profilePlan, setProfilePlan] = useState<ProfilePlan | null>(null);
  const [profilePlanMessage, setProfilePlanMessage] = useState("");
  const [profilePlanInProgress, setProfilePlanInProgress] = useState(false);
  const profilePlanGeneration = useRef(0);
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
  const incompatibleTargetReasons = new Map(
    controlSource?.incompatible_targets.map((target) => [
      target.ip,
      target.reason,
    ]) || [],
  );
  const eligibleTargetIps = controlSource
    ? controlSource.compatible_target_ips
    : devices.map((device) => device.ip);
  const allTargetsSelected =
    eligibleTargetIps.length > 0 &&
    eligibleTargetIps.every((ip) => selectedPushIps.includes(ip));
  const selectedDevices = devices.filter((device) =>
    selectedPushIps.includes(device.ip),
  );

  const invalidateProfilePlan = (message = "") => {
    profilePlanGeneration.current += 1;
    setProfilePlan(null);
    setProfilePlanInProgress(false);
    setProfilePlanMessage(message);
  };

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
    invalidateProfilePlan();
    setVerificationMessage("");
    setVerificationResults([]);
    setVerificationRequired(false);
    try {
      const url = `${backendBaseUrl}/discover-magewell?subnet=${encodeURIComponent(
        subnetToScan,
      )}&per_ip_timeout=3&max_concurrent=20&settings_timeout=5&rescan=${forceRescan}`;
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
    if (scanMode === "known-ips") {
      void scanKnownIps();
      return;
    }
    setControlMessage("");
    setControlSource(null);
    setSelectedControlDevice(null);
    setPushMessage("");
    void scanNetwork(subnet, true);
  };

  const scanKnownIps = async () => {
    const ips = knownIps.split(/[\s,]+/).filter(Boolean);
    setLoading(true);
    setError("");
    invalidateProfilePlan("Profile plan invalidated: discovery was requested.");
    try {
      const response = await fetch(`${backendBaseUrl}/discover-known-ips`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Magewell-Operator-Intent": "confirmed",
        },
        body: JSON.stringify({ ips }),
      });
      if (!response.ok) throw new Error(await apiError(response));
      const data = await response.json();
      setDevices(data.devices || []);
      setSelectedPushIps([]);
      setPushResults([]);
      setVerificationMessage("");
      setVerificationResults([]);
      setVerificationRequired(false);
      setControlSource(null);
      setSelectedControlDevice(null);
      setControlMessage(
        "Known-IP inventory loaded; select a live source to continue.",
      );
    } catch (scanError) {
      setError(
        scanError instanceof Error
          ? scanError.message
          : "Known-IP discovery failed.",
      );
    } finally {
      setLoading(false);
    }
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
    const blockedReason = incompatibleTargetReasons.get(device.ip);
    if (blockedReason) {
      setPushMessage(`Target ${device.ip} is blocked: ${blockedReason}`);
      return;
    }
    setSelectedPushIps((previous) =>
      previous.includes(device.ip)
        ? previous.filter((ip) => ip !== device.ip)
        : [...previous, device.ip],
    );
    invalidateProfilePlan(
      "Profile plan invalidated: target selection changed.",
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
    invalidateProfilePlan(
      "Profile plan invalidated: target selection changed.",
    );
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
    invalidateProfilePlan(
      "Profile plan invalidated: target selection changed.",
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
      invalidateProfilePlan("Profile plan invalidated: source changed.");
      setSelectedPushIps((previous) => {
        const compatibleIps = new Set(data.compatible_target_ips);
        return previous.filter((ip) => compatibleIps.has(ip));
      });
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

  const generateProfilePlan = async () => {
    if (!controlSource) {
      setProfilePlanMessage("Select and freeze the live control source first.");
      return;
    }
    const devicesToPlan = devices
      .filter((device) => selectedPushIps.includes(device.ip))
      .map((device) => ({ ip: device.ip, magewell_id: device.name }));
    if (devicesToPlan.length === 0) {
      setProfilePlanMessage(
        "Select at least one non-source target to preview.",
      );
      return;
    }
    const generation = profilePlanGeneration.current + 1;
    profilePlanGeneration.current = generation;
    setProfilePlan(null);
    setProfilePlanInProgress(true);
    setProfilePlanMessage(
      "Building a read-only compatibility plan from cached state...",
    );
    try {
      const response = await fetch(`${backendBaseUrl}/profile-plan`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Magewell-Operator-Intent": "confirmed",
        },
        body: JSON.stringify({ devices: devicesToPlan }),
      });
      if (!response.ok) throw new Error(await apiError(response));
      const data: ProfilePlan = await response.json();
      if (profilePlanGeneration.current !== generation) return;
      setProfilePlan(data);
      setProfilePlanMessage(
        data.all_targets_profile_compatible
          ? "Read-only plan is current. It does not simulate or authorize an import."
          : "Read-only plan is current, but one or more targets are not profile-compatible.",
      );
    } catch (planError) {
      if (profilePlanGeneration.current !== generation) return;
      setProfilePlan(null);
      setProfilePlanMessage(
        `Profile plan unavailable: ${
          planError instanceof Error ? planError.message : "unknown error"
        }`,
      );
    } finally {
      if (profilePlanGeneration.current === generation) {
        setProfilePlanInProgress(false);
      }
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

    invalidateProfilePlan(
      "Profile plan invalidated: a device write was requested; generate a fresh plan after verification.",
    );

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
      <div className={styles.topBar}>
        <h1>Encoders</h1>
        <span
          className={`${styles.writeStatus} ${
            writesEnabled ? styles.statusArmed : styles.statusLocked
          }`}
        >
          Writes: {writesEnabled ? "enabled" : "locked"}
        </span>
      </div>

      <section className={styles.scanPanel}>
        <form onSubmit={handleSubmit} className={styles.scanForm}>
          <div className={styles.fieldGroup}>
            <label htmlFor="scan-mode" className={styles.label}>
              Discovery mode
            </label>
            <select
              id="scan-mode"
              value={scanMode}
              onChange={(event: ChangeEvent<HTMLSelectElement>) =>
                setScanMode(event.target.value as "subnet" | "known-ips")
              }
              className={styles.input}
            >
              <option value="subnet">Allowed CIDR scan</option>
              <option value="known-ips">Known IPv4 list (read only)</option>
            </select>
          </div>
          <div className={styles.fieldGroup}>
            <label
              htmlFor={scanMode === "subnet" ? "subnet" : "known-ips"}
              className={styles.label}
            >
              {scanMode === "subnet"
                ? "Discovery subnet"
                : "Known IPv4 addresses"}
            </label>
            {scanMode === "subnet" ? (
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
            ) : (
              <textarea
                id="known-ips"
                value={knownIps}
                onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
                  setKnownIps(event.target.value)
                }
                className={`${styles.input} ${styles.knownIpsInput}`}
                placeholder="192.0.2.10, 192.0.2.11"
              />
            )}
          </div>
          <button
            type="submit"
            className={styles.primaryButton}
            disabled={loading}
          >
            {loading
              ? "Scanning…"
              : scanMode === "subnet"
                ? "Scan network"
                : "Read known IPs"}
          </button>
        </form>
        <span className={styles.inventoryCount}>
          {loading
            ? "Scanning…"
            : `${devices.length} encoder${devices.length === 1 ? "" : "s"}`}
        </span>
        {controlMessage && <p className={styles.notice}>{controlMessage}</p>}
        {error && <p className={styles.errorNotice}>{error}</p>}
      </section>

      {loading ? (
        <section className={styles.loadingState}>
          <p>
            {scanMode === "subnet"
              ? `Scanning ${subnet}…`
              : "Reading known IPs…"}
          </p>
        </section>
      ) : devices.length > 0 ? (
        <>
          <section className={styles.workflowPanel}>
            <div className={styles.sectionHeading}>
              <h2>Batch</h2>
              {verificationRequired && (
                <span className={styles.verifyRequired}>
                  Verify before writing again
                </span>
              )}
            </div>

            <div className={styles.workflowGrid}>
              <div className={styles.summaryCard}>
                <span className={styles.summaryLabel}>Source</span>
                <strong>{controlSource?.magewell_id || "Not selected"}</strong>
                <span className={styles.summaryMeta}>
                  {controlSource
                    ? `${controlSource.ip} · Profile ${shortHash(
                        controlSource.settings_sha256,
                      )}`
                    : "Choose a source from the encoder list"}
                </span>
              </div>
              <div className={styles.summaryCard}>
                <span className={styles.summaryLabel}>Targets</span>
                <strong>
                  {selectedPushIps.length} selected
                  {eligibleTargetIps.length > 0
                    ? ` of ${eligibleTargetIps.length}`
                    : ""}
                </strong>
                <span className={styles.summaryMeta}>
                  {selectedPushIps.length > 0
                    ? `${selectedDevices.length} encoder${selectedDevices.length === 1 ? "" : "s"} queued`
                    : "No targets selected"}
                </span>
              </div>
            </div>

            <div className={styles.actionRow}>
              <button
                onClick={generateProfilePlan}
                className={styles.secondaryButton}
                disabled={
                  profilePlanInProgress ||
                  !controlSource ||
                  selectedPushIps.length === 0
                }
              >
                {profilePlanInProgress
                  ? "Planning…"
                  : "Preview profile plan (read only)"}
              </button>
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

            {(profilePlanMessage || pushMessage || verificationMessage) && (
              <div className={styles.resultMessages}>
                {profilePlanMessage && <p>{profilePlanMessage}</p>}
                {pushMessage && <p>{pushMessage}</p>}
                {verificationMessage && <p>{verificationMessage}</p>}
              </div>
            )}
            {profilePlan && (
              <div className={styles.resultsList}>
                <div className={styles.resultRow}>
                  <span>
                    <strong>
                      Read-only plan {shortHash(profilePlan.plan_id)}
                    </strong>
                    <small>
                      Source {profilePlan.source.magewell_id} (
                      {profilePlan.source.ip})
                    </small>
                  </span>
                  <span
                    className={
                      profilePlan.all_targets_profile_compatible
                        ? styles.resultVerified
                        : styles.resultStopped
                    }
                  >
                    {profilePlan.all_targets_profile_compatible
                      ? "Compatible"
                      : "Review targets"}
                  </span>
                  <small>
                    Source {shortHash(profilePlan.source.settings_sha256)} ·
                    Inventory {shortHash(profilePlan.inventory_sha256)}
                  </small>
                </div>
                {profilePlan.targets.map((target) => (
                  <div className={styles.resultRow} key={`plan-${target.ip}`}>
                    <span>
                      <strong>{target.magewell_id}</strong>
                      <small>{target.ip}</small>
                    </span>
                    <span
                      className={
                        target.profile_compatible
                          ? styles.resultVerified
                          : styles.resultStopped
                      }
                    >
                      {target.profile_compatible ? "Compatible" : "Blocked"}
                    </span>
                    <small>
                      {target.profile_compatible
                        ? `Current ${shortHash(target.current_settings_sha256)} · Expected ${shortHash(target.expected_settings_sha256)}`
                        : target.compatibility_reason}
                    </small>
                  </div>
                ))}
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
              <h2>Inventory ({devices.length})</h2>
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
              incompatibleTargetReasons={incompatibleTargetReasons}
              onSelectToggle={handleSelectToggle}
              onSetControl={setSelectedControlDevice}
            />
          </section>
        </>
      ) : (
        <section className={styles.emptyState}>
          <p>No encoders loaded.</p>
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
            <h2>Set source</h2>
            <p>
              <strong>{selectedControlDevice.name || "Unnamed Device"}</strong>{" "}
              ({selectedControlDevice.ip})
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
                Set source
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
