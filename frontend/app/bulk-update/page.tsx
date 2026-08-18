"use client";

import { FormEvent, useEffect, useState } from "react";
import CustomFileInput from "@/components/CustomFileInput";
import styles from "@/app/page.module.css";

const backendBaseUrl = (
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");

interface UpdateResult {
  ip: string;
  magewell_id: string;
  status: string;
  error?: string;
}

async function apiError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body.detail || response.statusText;
  } catch {
    return response.statusText;
  }
}

export default function BulkUpdatePage() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState("");
  const [results, setResults] = useState<UpdateResult[]>([]);
  const [writesEnabled, setWritesEnabled] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const loadWriteStatus = async () => {
      try {
        const response = await fetch(`${backendBaseUrl}/healthz`);
        if (!response.ok) throw new Error("Backend status check failed.");
        const data = await response.json();
        setWritesEnabled(Boolean(data.device_writes_enabled));
      } catch (error) {
        console.error(error);
        setStatus("Backend is unavailable. Start it, then reload this page.");
      }
    };
    void loadWriteStatus();
  }, []);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file) {
      setStatus("Select a CSV file first.");
      return;
    }
    if (!writesEnabled) {
      setStatus("Device writes are locked by the backend configuration.");
      return;
    }
    const confirmed = window.confirm(
      `Apply the embedded baseline settings to every device listed in ${file.name}? This changes device configuration.`,
    );
    if (!confirmed) {
      setStatus("Bulk update cancelled; no write request was sent.");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    setSubmitting(true);
    setStatus("Updating devices from CSV...");
    setResults([]);
    try {
      const response = await fetch(
        `${backendBaseUrl}/bulk-update?confirm=true`,
        {
          method: "POST",
          headers: { "X-Magewell-Operator-Intent": "confirmed" },
          body: formData,
        },
      );
      if (!response.ok) throw new Error(await apiError(response));
      const data = await response.json();
      setResults(data.results || []);
      setStatus("Bulk update finished. Review every result below.");
    } catch (error) {
      setStatus(
        `Bulk update failed: ${error instanceof Error ? error.message : "unknown error"}`,
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={styles.page}>
      <div className={styles.headWrapper}>
        <h2>CSV Baseline Update</h2>
        <p>
          Required columns: <code>Magewell ID</code> and{" "}
          <code>Magewell IP</code>.
        </p>
        <p>Device writes: {writesEnabled ? "ENABLED" : "LOCKED"}</p>
      </div>
      <div className={styles.main}>
        <div className={styles.formWrapper}>
          <form onSubmit={handleSubmit}>
            <CustomFileInput onFileSelect={setFile} />
            <button
              className={styles.button28}
              type="submit"
              disabled={!writesEnabled || submitting}
            >
              {submitting ? "Updating..." : "Write Baseline Settings from CSV"}
            </button>
          </form>
        </div>
        {status && <div className={styles.statusBox}>{status}</div>}
        {results.length > 0 && (
          <ul className={styles.selectedList}>
            {results.map((result) => (
              <li key={result.ip}>
                {result.magewell_id} — {result.ip}: {result.status}
                {result.error ? ` (${result.error})` : ""}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
