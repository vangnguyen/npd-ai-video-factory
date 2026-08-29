import assert from "node:assert/strict";
import {mkdtempSync, rmSync, writeFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";

import {createLegacyTelemetry, readLegacyTelemetrySalt} from "./legacyTelemetry";

const rendered: string[] = [];
const record = createLegacyTelemetry("test-only-salt", (event) => rendered.push(JSON.stringify(event)));

const first = record({
  path: "/render",
  method: "POST",
  statusCode: 200,
  peerAddress: "203.0.113.10",
  claimedCallerId: "video-factory-v1-worker",
  userAgent: "private-agent/1.0",
});
const second = record({
  path: "/media/jobs/private/final.mp4",
  method: "GET",
  statusCode: 206,
  peerAddress: "203.0.113.10",
  claimedCallerId: "invalid caller",
  userAgent: "private-agent/1.0",
});
const unmatched = record({
  path: "/unmatched/private-value",
  method: "GET",
  statusCode: 404,
  peerAddress: "203.0.113.10",
});

assert(first !== null && second !== null);
assert.equal(first.source_fingerprint, second.source_fingerprint);
assert.equal(first.process_instance_id, second.process_instance_id);
assert.match(String(first.observed_at), /Z$/);
assert.equal(first.deprecated_attempt_count, 1);
assert.equal(second.deprecated_attempt_count, 2);
assert.equal(second.claimed_caller_id, "invalid");
assert.equal(second.route, "/media/{path}");
assert.equal(unmatched, null);
assert.equal(rendered.length, 2);
assert(!rendered.join("\n").includes("203.0.113.10"));
assert(!rendered.join("\n").includes("private-agent/1.0"));
assert(!rendered.join("\n").includes("test-only-salt"));

const secretDir = mkdtempSync(join(tmpdir(), "ah-t01-"));
try {
  const secretPath = join(secretDir, "telemetry-salt");
  writeFileSync(secretPath, `${"s".repeat(32)}\n`, "utf8");
  assert.equal(readLegacyTelemetrySalt({LEGACY_TELEMETRY_SALT_FILE: secretPath}), "s".repeat(32));
  assert.throws(
    () => readLegacyTelemetrySalt({
      LEGACY_TELEMETRY_SALT: "d".repeat(32),
      LEGACY_TELEMETRY_SALT_FILE: secretPath,
    }),
    /only one/,
  );
  assert.throws(() => readLegacyTelemetrySalt({LEGACY_TELEMETRY_SALT: "short"}), /32 bytes/);
} finally {
  rmSync(secretDir, {recursive: true, force: true});
}

console.log("legacy renderer telemetry smoke passed: events=2 raw_identity=false payload=false");
