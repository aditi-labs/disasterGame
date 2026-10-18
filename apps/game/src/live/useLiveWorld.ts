import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_URL, SCENARIO_ID } from "../config";
import type { ActionResult, Envelope, HealthResponse, ObjectObservation, PhysicalFeedback, ProjectionRegistration, TokenType, UV, WorldAction, WorldSnapshot } from "../types/contracts";
import type { ScenarioGeometry } from "../types/scenario";
import { setBoardAspect } from "../types/geometry";
import { diffSnapshots, type ReactionSet } from "../game/reactions";
import { createLiveTransport, newActionId, nowUtc, type ConnectionStatus, type PerceptionStatus, type WorldTransport } from "./transport";

// One live-data path for both screens. Snapshots come only from the retained
// WorldService; on any failure the UI reports it instead of drawing a world.

/** How long one snapshot's environmental cues stay on the board (effects ≤ ~2 s, labels ~1.5 s). */
export const REACTION_MS = 3200;
/** A camera candidate not re-reported within this window stops being drawn. */
export const PENDING_TTL_MS = 2500;

export interface ActiveReaction extends ReactionSet {
  at: number;
  until: number;
}

/** Where an action came from, as shown in operator logs (spec §3 rule 4). */
export type Provenance = "operator_manual" | "game_setup" | "game_clock";

export interface RunEvent {
  at: string;
  provenance: Provenance;
  action: WorldAction | { type: "reset" };
  accepted: boolean;
  reason: string | null;
  versionBefore: number;
  versionAfter: number;
}

export interface LogEntry {
  at: string;
  kind: "accepted" | "rejected" | "info" | "warning" | "vision" | "reaction";
  text: string;
}

let shared: WorldTransport | null = null;
function transport(): WorldTransport {
  shared ??= createLiveTransport(API_URL);
  return shared;
}

async function sha256(text: string): Promise<string | null> {
  try {
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
  } catch {
    return null;
  }
}

export function useLiveWorld({ pollHealth = false }: { pollHealth?: boolean } = {}) {
  const t = useMemo(transport, []);
  const [snapshot, setSnapshot] = useState<WorldSnapshot | null>(null);
  const [scenario, setScenario] = useState<ScenarioGeometry | null>(null);
  const [scenarioError, setScenarioError] = useState<string | null>(null);
  const [fingerprint, setFingerprint] = useState<string | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [perception, setPerception] = useState<PerceptionStatus | null>(null);
  const [observations, setObservations] = useState<Map<string, ObjectObservation & { seenAt: number }>>(new Map());
  const [visionLatency, setVisionLatency] = useState<number | null>(null);
  const [reactions, setReactions] = useState<ActiveReaction[]>([]);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [run, setRun] = useState<RunEvent[]>([]);
  const [inFlight, setInFlight] = useState(0);
  const [loadCount, setLoadCount] = useState(0);
  const [registration, setRegistration] = useState<ProjectionRegistration | null>(null);
  const [physicalFeedback, setPhysicalFeedback] = useState<(PhysicalFeedback & { until: number })[]>([]);
  const [footprints, setFootprints] = useState<Record<string, UV[]>>({});

  const lastSeq = useRef(-Infinity);
  const snapRef = useRef<WorldSnapshot | null>(null);
  const scenarioRef = useRef<ScenarioGeometry | null>(null);
  const knownVersion = useRef(0);
  const newConnection = useRef(true);
  const reacted = useRef(new Set<string>());

  const push = useCallback((kind: LogEntry["kind"], text: string) => {
    setLog((l) => [{ at: new Date().toLocaleTimeString(), kind, text }, ...l].slice(0, 200));
  }, []);

  const react = useCallback(
    (prev: WorldSnapshot | null, next: WorldSnapshot) => {
      const sc = scenarioRef.current;
      if (!sc) return;
      const set = diffSnapshots(prev, next, sc);
      if (!set || reacted.current.has(set.key)) return;
      reacted.current.add(set.key);
      if (!set.cues.length && !set.headline) return;
      const now = Date.now();
      setReactions((list) => [...list.filter((r) => r.until > now), { ...set, at: now, until: now + REACTION_MS }]);
      window.setTimeout(() => setReactions((list) => list.filter((r) => r.key !== set.key)), REACTION_MS);
      if (set.headline) push("reaction", `${set.headline.text}${set.scoreDelta ? ` (score ${set.scoreDelta > 0 ? "+" : ""}${set.scoreDelta})` : ""}`);
    },
    [push],
  );

  // Geometry is static per scenario, but the server may start after the UI.
  useEffect(() => {
    let cancelled = false;
    const load = () => fetch(t.baseUrl + "/projection/registration").then(r => {
      if (!r.ok) throw new Error("registration unavailable");
      return r.json();
    }).then(r => { if (!cancelled) { setRegistration(r); setFootprints(r.occlusions ?? {}); } }).catch(() => { if (!cancelled) setRegistration(null); });
    void load();
    const id = window.setInterval(load, 2000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [t]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const load = () =>
      fetch(t.baseUrl + "/scenario")
        .then(async (res) => {
          if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
          const text = await res.text();
          const s = JSON.parse(text) as ScenarioGeometry;
          if (cancelled) return;
          if (s.scenario_id !== SCENARIO_ID) throw new Error(`server scenario ${s.scenario_id} ≠ configured ${SCENARIO_ID}`);
          setBoardAspect(s.aspect_ratio);
          scenarioRef.current = s;
          setScenario(s);
          setScenarioError(null);
          setFingerprint(await sha256(text));
        })
        .catch((err: Error) => {
          if (cancelled) return;
          setScenarioError(`GET ${t.baseUrl}/scenario failed: ${err.message}`);
          timer = window.setTimeout(load, 2000);
        });
    load();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [t, loadCount]);

  useEffect(() => {
    const onEnvelope = (e: Envelope) => {
      // A new connection (possibly to a restarted server) restarts the sequence.
      if (e.type === "server.hello") {
        lastSeq.current = -Infinity;
        newConnection.current = true;
      }
      if (typeof e.seq === "number" && e.seq > 0 && e.seq <= lastSeq.current) return;
      if (typeof e.seq === "number" && e.seq > 0) lastSeq.current = e.seq;
      switch (e.type) {
        case "world.snapshot": {
          const prev = snapRef.current;
          if (!newConnection.current && prev && e.payload.branch_id === prev.branch_id && e.payload.world_version < prev.world_version) return;
          const restarted = newConnection.current && prev && e.payload.world_version < prev.world_version;
          const freshConnection = newConnection.current;
          newConnection.current = false;
          snapRef.current = e.payload;
          knownVersion.current = freshConnection ? e.payload.world_version : Math.max(knownVersion.current, e.payload.world_version);
          setSnapshot(e.payload);
          if (e.payload.phase === "ready") { setPhysicalFeedback([]); setFootprints({}); }
          if (restarted) {
            reacted.current.clear();
            setReactions([]);
            setObservations(new Map());
          } else react(prev, e.payload);
          break;
        }
        case "vision.status": {
          const now = Date.now();
          const feedback = e.payload.physical_feedback;
          if (feedback) {
            if (feedback.footprint_key && feedback.print_footprint) setFootprints(old => {
              const next = { ...old };
              if (feedback.print_footprint!.length) next[feedback.footprint_key!] = feedback.print_footprint!;
              else delete next[feedback.footprint_key!];
              return next;
            });
            setPhysicalFeedback(list => [...list.filter(f => f.until > now && f.track_id !== feedback.track_id), { ...feedback, until: now + (feedback.status === "pending" ? PENDING_TTL_MS : 1800) }]);
            push("vision", `${feedback.track_id} ${feedback.status}: ${feedback.rejection_reason ?? feedback.world_token_id ?? ""}`);
          }
          setObservations((m) => {
            const next = new Map([...m].filter(([, o]) => now - o.seenAt < PENDING_TTL_MS));
            for (const o of e.payload.observations) next.set(o.token_id, { ...o, seenAt: now });
            return next;
          });
          setVisionLatency(e.payload.latency_ms ?? null);
          for (const o of e.payload.observations) push("vision", `${o.object_type} ${o.vision_status} (${o.class_source}) track ${o.token_id} uv [${o.board_uv.map((n) => n.toFixed(3)).join(", ")}]`);
          break;
        }
        case "warning":
          push("warning", e.payload.message);
          break;
        case "server.hello":
          push("info", `server: ${e.payload.status}`);
          break;
        default:
          break;
      }
    };
    return t.connect(onEnvelope, setStatus);
  }, [t, push, react]);

  // Pending candidates age out even when no new vision message arrives.
  useEffect(() => {
    const id = window.setInterval(() => {
      const now = Date.now();
      setObservations((m) => (([...m.values()].some((o) => now - o.seenAt >= PENDING_TTL_MS)) ? new Map([...m].filter(([, o]) => now - o.seenAt < PENDING_TTL_MS)) : m));
    }, 500);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!pollHealth) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const h = await t.health();
        if (!cancelled) {
          setHealth(h);
          setHealthError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setHealth(null);
          setHealthError((err as Error).message);
        }
      }
      try {
        const p = await t.perceptionStatus();
        if (!cancelled) setPerception(p);
      } catch {
        if (!cancelled) setPerception(null);
      }
    };
    void tick();
    const id = window.setInterval(tick, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [t, pollHealth]);

  /** LOAD LIVE SCENARIO: re-read geometry and the current authoritative snapshot. */
  const reload = useCallback(async () => {
    setLoadCount((n) => n + 1);
    try {
      const w = await t.getWorld();
      if (w.scenario_id !== SCENARIO_ID) throw new Error(`server scenario ${w.scenario_id} ≠ configured ${SCENARIO_ID}`);
      const prev = snapRef.current;
      snapRef.current = w;
      knownVersion.current = Math.max(knownVersion.current, w.world_version);
      setSnapshot(w);
      if (prev) react(prev, w);
      push("info", `loaded live scenario ${w.scenario_id} at world ${w.world_version}`);
      return true;
    } catch (err) {
      push("warning", `LOAD LIVE SCENARIO failed: ${(err as Error).message}`);
      return false;
    }
  }, [t, push, react]);

  const record = useCallback((ev: RunEvent) => setRun((r) => [...r, ev]), []);

  /**
   * Send one WorldAction through the authoritative reducer. A stale version is
   * reconciled by re-reading /world and retrying the same action id once; it is never
   * silently dropped or double-applied (the backend dedups action ids).
   */
  const send = useCallback(
    async (
      partial: Omit<WorldAction, "expected_world_version" | "timestamp_utc" | "source" | "action_id"> & { action_id?: string },
      provenance: Provenance = "operator_manual",
    ): Promise<ActionResult | null> => {
      const action: WorldAction = {
        ...partial,
        action_id: partial.action_id ?? newActionId(partial.type),
        source: "manual",
        expected_world_version: knownVersion.current,
        timestamp_utc: nowUtc(),
      };
      const label = `${action.type}${action.token_type ? " " + action.token_type : ""}${action.site_id ? " @ " + action.site_id : ""}${action.token_id && action.type !== "place_token" ? " " + action.token_id : ""}`;
      setInFlight((n) => n + 1);
      try {
        let r = await t.sendAction(action);
        if (!r.accepted && r.rejection_reason === "stale_version") {
          const w = await t.getWorld();
          knownVersion.current = Math.max(knownVersion.current, w.world_version);
          action.expected_world_version = w.world_version;
          r = await t.sendAction(action);
        }
        knownVersion.current = Math.max(knownVersion.current, r.world_version);
        record({ at: nowUtc(), provenance, action: { ...action }, accepted: r.accepted, reason: r.rejection_reason ?? null, versionBefore: action.expected_world_version, versionAfter: r.world_version });
        push(r.accepted ? "accepted" : "rejected", `[${provenance}] ${label} → ${r.accepted ? `world ${r.world_version}` : `rejected: ${r.rejection_reason}`}`);
        return r;
      } catch (err) {
        push("warning", `POST /action failed (${label}): ${(err as Error).message}`);
        return null;
      } finally {
        setInFlight((n) => n - 1);
      }
    },
    [t, push, record],
  );

  const reset = useCallback(
    async (provenance: Provenance = "operator_manual") => {
      setInFlight((n) => n + 1);
      try {
        const before = knownVersion.current;
        const r = await t.reset();
        knownVersion.current = Math.max(knownVersion.current, r.world_version);
        record({ at: nowUtc(), provenance, action: { type: "reset" }, accepted: r.reset, reason: r.reset ? null : "reset_rejected", versionBefore: before, versionAfter: r.world_version });
        push(r.reset ? "accepted" : "rejected", `[${provenance}] reset → world ${r.world_version}`);
        if (r.reset) {
          reacted.current.clear();
          setReactions([]);
          setObservations(new Map());
        }
        return r;
      } catch (err) {
        push("warning", `POST /reset failed: ${(err as Error).message}`);
        return null;
      } finally {
        setInFlight((n) => n - 1);
      }
    },
    [t, push, record],
  );

  const suggest = useCallback(async (goal = "needs_served", provenance = "operator_manual") => {
    try {
      const r = await t.suggest(goal);
      push(r.has_suggestion ? "accepted" : "rejected", `[${provenance}] suggest bridge (${goal}) → ${r.has_suggestion ? `site ${r.suggestion?.site_id}` : r.rejection_reason ?? "no_suggestion"}`);
      return r;
    } catch (err) {
      push("warning", `POST /plan/suggest failed: ${(err as Error).message}`);
      return null;
    }
  }, [t, push]);

  const place = useCallback(
    (token_type: TokenType, site_id: string, board_uv: UV, token_id: string, provenance: Provenance = "operator_manual", action_id?: string) =>
      send({ type: "place_token", token_type, site_id, board_uv, token_id, action_id }, provenance),
    [send],
  );
  const move = useCallback((token_id: string, site_id: string, board_uv: UV) => send({ type: "move_token", token_id, site_id, board_uv }), [send]);
  const remove = useCallback((token_id: string) => send({ type: "remove_token", token_id }), [send]);
  const advanceStage = useCallback((action_id?: string, provenance: Provenance = "operator_manual") => send({ type: "advance_stage", action_id }, provenance), [send]);

  const clearPending = useCallback((tokenIds?: string[]) => {
    setObservations((m) => (tokenIds ? new Map([...m].filter(([id]) => !tokenIds.includes(id))) : new Map()));
    setPhysicalFeedback(list => list.filter(f => f.status !== "pending" || (tokenIds && !tokenIds.includes(f.track_id))));
  }, []);

  const scenarioMismatch = !!snapshot && snapshot.scenario_id !== SCENARIO_ID;

  return {
    registration,
    physicalFeedback,
    footprints,
    controlRun: t.controlRun,
    apiUrl: t.baseUrl,
    scenarioId: SCENARIO_ID,
    snapshot: scenarioMismatch ? null : snapshot,
    scenarioMismatch,
    scenario,
    scenarioError,
    fingerprint,
    status,
    health,
    healthError,
    perception,
    observations,
    visionLatency,
    reactions,
    log,
    run,
    inFlight,
    push,
    send,
    reset,
    reload,
    suggest,
    place,
    move,
    remove,
    advanceStage,
    clearPending,
    knownVersion: () => knownVersion.current,
  };
}

export type LiveWorld = ReturnType<typeof useLiveWorld>;
