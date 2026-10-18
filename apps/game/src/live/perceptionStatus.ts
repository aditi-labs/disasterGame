import type { PerceptionStatus } from "./transport";

export type StatusTone = "ok" | "warn" | "bad";
export interface StatusBadge { value: string; tone: StatusTone }
const record = (v: unknown): Record<string, unknown> => v && typeof v === "object" && !Array.isArray(v) ? v as Record<string, unknown> : {};
const scalar = (v: unknown) => typeof v === "string" || typeof v === "number" || typeof v === "boolean" ? String(v) : null;
const connected = (s: string) => /^(connected|ok|live|running|calibrated|available)$/i.test(s);

/** Accept Lane B's nested telemetry and the retained gateway's legacy status strings. */
export function perceptionView(status: PerceptionStatus | null, legacyPerceptron?: string) {
  const p = status ?? {};
  const cam = record(p.camera), reg = record(p.registration), classifier = record(p.classifier);
  const cameraLegacy = scalar(p.camera) ?? "not reported";
  const camera: StatusBadge = typeof cam.connected === "boolean"
    ? { value: cam.connected ? "LIVE" : "DOWN", tone: cam.connected ? "ok" : "bad" }
    : { value: cameraLegacy.toUpperCase(), tone: connected(cameraLegacy) ? "ok" : "warn" };
  const arucoLegacy = scalar(p.calibration) ?? "not reported";
  const registrationReady = reg.valid === true && reg.registration_verified === true && reg.held !== true && reg.degraded !== true;
  const aruco: StatusBadge = typeof reg.valid === "boolean"
    ? { value: reg.valid !== true ? "UNREGISTERED" : reg.degraded === true ? "DEGRADED" : reg.held === true ? "HELD" : reg.registration_verified !== true ? "VALID · UNMEASURED" : "CALIBRATED", tone: registrationReady ? "ok" : "warn" }
    : { value: arucoLegacy.toUpperCase(), tone: connected(arucoLegacy) ? "ok" : "warn" };
  const classifierKind = scalar(classifier.kind) ?? "";
  const perceptronLegacy = scalar(p.perceptron) ?? legacyPerceptron ?? "not reported";
  const perceptron: StatusBadge = Object.keys(classifier).length > 0
    ? { value: /perceptron/i.test(classifierKind) && classifier.available === true ? "AVAILABLE" : "NOT CONNECTED", tone: /perceptron/i.test(classifierKind) && classifier.available === true ? "ok" : "warn" }
    : { value: perceptronLegacy.toUpperCase(), tone: connected(perceptronLegacy) ? "ok" : "warn" };
  return { camera, aruco, perceptron, registrationReady,
    markerIds: reg.markers_used ?? p.marker_ids ?? p.markers ?? p.corners_found,
    rmsUv: reg.reprojection_rms_uv, rmsPx: reg.reprojection_rms_px ?? p.reprojection_error_px ?? p.reprojection_error,
    cameraSource: scalar(cam.source), fps: scalar(cam.fps_measured), frameAgeMs: scalar(cam.last_frame_age_ms),
    registrationReason: scalar(reg.reason), registrationStatus: scalar(reg.registration_status),
  };
}
