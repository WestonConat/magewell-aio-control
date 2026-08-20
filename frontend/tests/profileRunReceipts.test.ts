import assert from "node:assert/strict";
import test from "node:test";

import {
  isReceiptDisplaySafe,
  receiptHasUncertainRisk,
  receiptTargetSummary,
  type ProfileRunReceipt,
} from "../app/profileRunReceipts.ts";

const receipt: ProfileRunReceipt = {
  receipt_id: "a".repeat(32),
  created_at: "2026-08-20T00:00:00Z",
  run_state: "mutation-finished",
  source: {
    ip: "192.0.2.10",
    magewell_id: "SOURCE-01",
    settings_sha256: "b".repeat(64),
  },
  targets: [
    {
      ip: "192.0.2.11",
      magewell_id: "TARGET-01",
      expected_settings_sha256: "c".repeat(64),
      mutation: { status: "updated", reason_code: "import-accepted" },
      verification: { status: "not-requested", reason_code: "write-pending" },
      risk_state: "verification-pending",
    },
    {
      ip: "192.0.2.12",
      magewell_id: "TARGET-02",
      expected_settings_sha256: "d".repeat(64),
      mutation: { status: "failed", reason_code: "mutation-response-unknown" },
      verification: { status: "not-requested", reason_code: "write-pending" },
      risk_state: "uncertain-high-risk",
    },
  ],
};

test("receipt inspection preserves per-target outcome order and highlights uncertainty", () => {
  assert.equal(receiptHasUncertainRisk(receipt), true);
  assert.equal(
    receiptTargetSummary(receipt),
    "TARGET-01: updated/not-requested · TARGET-02: failed/not-requested",
  );
});

test("receipt inspection refuses secret-bearing or raw device-shaped payloads", () => {
  assert.equal(isReceiptDisplaySafe(receipt), true);
  assert.equal(
    isReceiptDisplaySafe({
      ...receipt,
      settings: { passwd: "must-not-render" },
    }),
    false,
  );
  assert.equal(
    isReceiptDisplaySafe({
      ...receipt,
      source: { ...receipt.source, url: "http://device" },
    }),
    false,
  );
  assert.equal(
    isReceiptDisplaySafe({ ...receipt, cookie: "must-not-render" }),
    false,
  );
});
