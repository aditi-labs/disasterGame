import { expect, it } from "vitest";
import { perceptionView } from "../src/live/perceptionStatus";

// Shapes produced by Lane B's PerceptionService.status / RegistrationState.as_status.
const reported = {
  camera: { connected: true, source: "recording:board", fps_measured: 29.7, last_frame_age_ms: 12 },
  registration: { valid: true, registration_verified: false, held: false, degraded: false,
    markers_used: [10, 11, 12, 13], reprojection_rms_uv: 0.003, reprojection_rms_px: 1.2,
    registration_status: "UNVERIFIED_TENTATIVE" },
  classifier: { kind: "none", available: false },
};

it("reads Lane B's nested camera, registration and RMS fields", () => {
  const view = perceptionView(reported);
  expect(view.camera).toEqual({ value: "LIVE", tone: "ok" });
  expect(view.aruco).toEqual({ value: "VALID · UNMEASURED", tone: "warn" });
  expect(view.registrationReady).toBe(false);
  expect(view.markerIds).toEqual([10, 11, 12, 13]);
  expect(view.rmsUv).toBe(0.003);
  expect(view.rmsPx).toBe(1.2);
  expect(view.perceptron.tone).toBe("warn");
});
it("requires measured registration and rejects held/degraded poses as calibrated", () => {
  const measured = { ...reported, registration: { ...reported.registration, registration_verified: true } };
  expect(perceptionView(measured).registrationReady).toBe(true);
  expect(perceptionView({ ...measured, registration: { ...measured.registration, held: true } }).registrationReady).toBe(false);
  expect(perceptionView({ ...measured, registration: { ...measured.registration, degraded: true } }).aruco.value).toBe("DEGRADED");
});
it("does not label an available local classifier as Perceptron", () => {
  expect(perceptionView({ ...reported, classifier: { kind: "operator", available: true } }).perceptron.tone).toBe("warn");
  expect(perceptionView({ ...reported, classifier: { kind: "perceptron", available: true } }).perceptron.tone).toBe("ok");
});
it("keeps gateway legacy telemetry compatible without treating disconnected as connected", () => {
  const legacy = perceptionView({ camera: "not_connected", calibration: "not_calibrated" }, "disconnected");
  expect(legacy.camera.tone).toBe("warn");
  expect(legacy.aruco.tone).toBe("warn");
  expect(legacy.perceptron.tone).toBe("warn");
  expect(perceptionView(null).camera.value).toBe("NOT REPORTED");
});
