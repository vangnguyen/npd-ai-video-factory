import {createHmac} from "node:crypto";

const callerIdPattern = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/;

type LegacyRoute = "/healthz" | "/render" | "/media/{path}";

const routeAction: Record<LegacyRoute, string> = {
  "/healthz": "health_probe",
  "/render": "legacy_render",
  "/media/{path}": "legacy_media_read",
};

const resolveRoute = (path: string): LegacyRoute | null => {
  if (path === "/healthz" || path === "/render") return path;
  if (path.startsWith("/media/")) return "/media/{path}";
  return null;
};

const safeClaimedCaller = (value: string | undefined): string | null => {
  if (value === undefined) return null;
  const candidate = value.trim();
  return callerIdPattern.test(candidate) ? candidate : "invalid";
};

const fingerprint = (value: string, salt: string | undefined): string | null => {
  if (!salt) return null;
  return `hmac-sha256:${createHmac("sha256", salt).update(value).digest("hex").slice(0, 24)}`;
};

export type LegacyTelemetryInput = {
  path: string;
  method: string;
  statusCode: number;
  peerAddress?: string;
  claimedCallerId?: string;
  userAgent?: string;
};

export const createLegacyTelemetry = (
  salt: string | undefined,
  emit: (event: Record<string, unknown>) => void = (event) => console.log(JSON.stringify(event)),
) => {
  const routeCounts = new Map<LegacyRoute, number>();
  let deprecatedAttemptCount = 0;

  return (input: LegacyTelemetryInput): Record<string, unknown> | null => {
    const route = resolveRoute(input.path);
    if (route === null) return null;
    const action = routeAction[route];
    const deprecatedAttempt = action !== "health_probe";
    const routeRequestCount = (routeCounts.get(route) ?? 0) + 1;
    routeCounts.set(route, routeRequestCount);
    if (deprecatedAttempt) deprecatedAttemptCount += 1;

    const peer = input.peerAddress ?? "unavailable";
    const agent = input.userAgent ?? "unavailable";
    const event: Record<string, unknown> = {
      event: "legacy_route_access",
      service: "video-factory-v1-renderer",
      route,
      method: input.method.toUpperCase(),
      status_code: input.statusCode,
      action,
      deprecated_attempt: deprecatedAttempt,
      claimed_caller_id: safeClaimedCaller(input.claimedCallerId),
      source_fingerprint: fingerprint(peer, salt),
      client_fingerprint: fingerprint(`${peer}\n${agent}`, salt),
      identity_ready: Boolean(salt),
      route_request_count: routeRequestCount,
      deprecated_attempt_count: deprecatedAttemptCount,
      payload_logged: false,
      raw_network_identity_logged: false,
    };
    emit(event);
    return event;
  };
};
