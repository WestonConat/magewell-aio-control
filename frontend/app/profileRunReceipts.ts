export interface ProfileRunReceiptTarget {
  ip: string;
  magewell_id: string;
  expected_settings_sha256: string;
  mutation: { status: string; reason_code: string };
  verification: { status: string; reason_code: string; attempts?: number };
  risk_state: string;
}

export interface ProfileRunReceipt {
  receipt_id: string;
  created_at: string;
  run_state: string;
  source: { ip: string; magewell_id: string; settings_sha256: string };
  targets: ProfileRunReceiptTarget[];
}

const forbiddenKeys = new Set([
  "settings",
  "password",
  "passwd",
  "credential",
  "credentials",
  "cookie",
  "cookies",
  "header",
  "headers",
  "url",
  "urls",
  "response",
  "responses",
  "query",
  "error",
  "errors",
]);

function isRedactedValue(value: unknown): boolean {
  if (Array.isArray(value)) return value.every(isRedactedValue);
  if (!value || typeof value !== "object") return true;
  return Object.entries(value).every(([key, nested]) => {
    const normalized = key.toLowerCase().replaceAll("-", "_");
    return (
      !forbiddenKeys.has(normalized) &&
      !(normalized.includes("settings") && !normalized.endsWith("sha256")) &&
      isRedactedValue(nested)
    );
  });
}

export function isReceiptDisplaySafe(
  value: unknown,
): value is ProfileRunReceipt {
  return isRedactedValue(value);
}

export function receiptHasUncertainRisk(receipt: ProfileRunReceipt): boolean {
  return receipt.targets.some(
    (target) =>
      target.risk_state === "uncertain-high-risk" ||
      target.risk_state === "verification-pending",
  );
}

export function receiptTargetSummary(receipt: ProfileRunReceipt): string {
  return receipt.targets
    .map(
      (target) =>
        `${target.magewell_id}: ${target.mutation.status}/${target.verification.status}`,
    )
    .join(" · ");
}
