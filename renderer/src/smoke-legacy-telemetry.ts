import assert from "node:assert/strict";

import {createLegacyTelemetry} from "./legacyTelemetry";

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
assert.equal(first.deprecated_attempt_count, 1);
assert.equal(second.deprecated_attempt_count, 2);
assert.equal(second.claimed_caller_id, "invalid");
assert.equal(second.route, "/media/{path}");
assert.equal(unmatched, null);
assert.equal(rendered.length, 2);
assert(!rendered.join("\n").includes("203.0.113.10"));
assert(!rendered.join("\n").includes("private-agent/1.0"));
assert(!rendered.join("\n").includes("test-only-salt"));

console.log("legacy renderer telemetry smoke passed: events=2 raw_identity=false payload=false");
