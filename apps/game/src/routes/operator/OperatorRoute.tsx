import { useEffect, useMemo, useState } from "react";
import { useLiveWorld } from "../../live/useLiveWorld";
import { perceptionView } from "../../live/perceptionStatus";
import type { TokenType, WorldSnapshot } from "../../types/contracts";
import { TOKEN_SITE_KIND } from "../../types/contracts";
import type { ScenarioGeometry } from "../../types/scenario";
import { MARKER_LAYOUT_VERIFIED, MARKER_PROVENANCE, PRINT_WORLD_ALIGNMENT_NOTE } from "../../game/board";
import { BOUNDARIES_S, MISSION_MS } from "../../game/clock";
import { BoardSvg } from "../../game/overlays/BoardSvg";
import { PieceIcon } from "../../game/overlays/glyphs";
import { buildResults } from "../../game/results";
import { isMuted, setMuted } from "../../game/sound";
import { BEATS, CONNECTION_LOST, FLOOD_UPDATE_UNAVAILABLE, GAME_PIECES, LIVE_DATA_UNAVAILABLE, PIECE_NAME } from "../../game/story";
import { buildBoardModel, peopleReachable, SERVICES, totalNeed, totalPeople, unmetNeed } from "../../game/worldAdapter";
import { useMission, type Mission } from "./useMission";
import { StartScreen } from "./StartScreen";

// /operator — the laptop view (spec §9 "Operator UI"). Every control maps to one
// authoritative backend action; numbers are read from the latest snapshot only.
// Manual actions are physical-I/O fallbacks and are logged as operator_manual.

type Tone = "ok" | "warn" | "bad" | "neutral";

function Status({ label, value, tone, title }: { label: string; value: string; tone: Tone; title?: string }) {
  return (
    <span className={`status status-${tone}`} title={title}>
      <span className="status-label">{label}</span>
      <span className="status-value">{value}</span>
    </span>
  );
}

const NEED_LABEL = { refuge: "Refuge", medical: "Medical", food: "Food" } as const;
const KEY_PIECES: Record<string, TokenType> = { "3": "hospital", "4": "food_shelter", "5": "shelter", "6": "bridge" };

export function OperatorRoute() {
  const world = useLiveWorld({ pollHealth: true });
  const mission = useMission(world);
  const [debug, setDebug] = useState(false);
  const [muted, setMutedState] = useState(isMuted);
  const [piece, setPiece] = useState<TokenType>("bridge");
  const [placeSite, setPlaceSite] = useState<string>("");
  const [moveToken, setMoveToken] = useState<string>("");
  const [moveSite, setMoveSite] = useState<string>("");
  const [showCamera, setShowCamera] = useState(false);

  const { snapshot, scenario, status, health, healthError, perception, fingerprint, scenarioError, scenarioMismatch } = world;
  const { phase, view, inputOpen, clock } = mission;
  const beat = BEATS[phase];
  const running = clock.mode === "running";
  const paused = clock.mode === "paused";
  const inMission = running || paused;
  const finished = clock.mode === "finished";
  const preStart = clock.mode === "idle" || clock.mode === "intro";
  const liveData = !!scenario && !!snapshot && !scenarioMismatch && !healthError;
  const connected = status === "live";
  const busy = mission.starting || world.inFlight > 0;
  const [tools, setTools] = useState(() => new URLSearchParams(window.location.search).get("tools") === "1");
  const resultSnapshot = mission.finalSnapshot ?? snapshot;

  const model = useMemo(
    () => (scenario && snapshot ? buildBoardModel(scenario, snapshot, inMission ? beat.pieces : [], inputOpen) : null),
    [scenario, snapshot, beat.pieces, inputOpen, inMission],
  );
  const results = useMemo(() => (scenario && resultSnapshot ? buildResults(scenario, resultSnapshot) : null), [scenario, resultSnapshot]);

  // Keys 3–6 only in diagnostic/manual mode (spec: never active player instructions).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (["INPUT", "SELECT", "TEXTAREA"].includes(target?.tagName) || target?.isContentEditable || e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
      if (e.key.toLowerCase() === "o") return setTools(v => !v);
      if (!debug) return;
      if (KEY_PIECES[e.key]) setPiece(KEY_PIECES[e.key]);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [debug]);

  const sitesFor = (type: TokenType) => (scenario ? scenario.sites.filter((s) => s.kind === TOKEN_SITE_KIND[type]) : []);
  const gamePieces = snapshot?.tokens.filter((t) => GAME_PIECES.includes(t.type)) ?? [];
  const moving = gamePieces.find((t) => t.id === moveToken);

  const onSiteClick = (siteId: string) => {
    if (!scenario || !inputOpen) return;
    const site = scenario.sites.find((s) => s.id === siteId);
    if (!site) return;
    if (moving && site.kind === TOKEN_SITE_KIND[moving.type]) {
      void mission.manual.move(moving.id, site.id, site.board_uv);
      setMoveToken("");
      return;
    }
    const type = site.kind === TOKEN_SITE_KIND[piece] ? piece : GAME_PIECES.find((p) => TOKEN_SITE_KIND[p] === site.kind);
    if (type) void mission.manual.place(type, site.id, site.board_uv);
  };

  const projectorSeen = mission.projector && Date.now() - mission.projector.seenAt < 3000;
  const projectorValue = !projectorSeen ? "NOT OPEN" : !mission.projector!.overlay ? "SCREEN" : !mission.projector!.alignmentVerified ? "ALIGNMENT REQUIRED" : mission.projector!.calibratedAt ? "CALIBRATED" : "UNCALIBRATED";
  const telemetry = perceptionView(perception, health?.perceptron_status);
  const alignmentReady = world.registration?.ready === true;

  const downloadRun = () => {
    const record = {
      kind: "floodshift.game.run",
      scenario_id: world.scenarioId,
      scenario_fingerprint_sha256: fingerprint,
      fingerprint_basis: "client sha256 of the GET /scenario response body",
      api: world.apiUrl,
      session_id: clock.sessionId,
      started_at: mission.startedAt,
      exported_at: new Date().toISOString(),
      final_world_version: resultSnapshot?.world_version ?? null,
      final_phase: phase,
      surge: clock.surge,
      marker_registration: { verified: alignmentReady, layout_verified_from_photo: MARKER_LAYOUT_VERIFIED, print_world_alignment_verified: alignmentReady, provenance: MARKER_PROVENANCE },
      events: world.run,
      final_game: resultSnapshot?.game ?? null,
      final_metrics: resultSnapshot?.metrics ?? null,
    };
    const blob = new Blob([JSON.stringify(record, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${clock.sessionId ?? "floodshift-run"}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  if (!tools) {
    return <StartScreen mode={clock.mode} phase={phase} remainingMs={view.remainingMs} ready={liveData && connected} starting={busy} physicalInputReady={telemetry.camera.tone === "ok" && telemetry.registrationReady && telemetry.perceptron.tone === "ok" && alignmentReady} error={mission.startError ?? (!liveData ? scenarioError ?? healthError ?? null : null)} onStart={() => void mission.startGame()} />;
  }

  return (
    <div className="operator">
      <header className="op-header">
        <div className="op-brand">
          <b>FLOODSHIFT</b> <span>operator</span>
        </div>
        <button className="btn btn-sm btn-quiet" onClick={() => setTools(false)}>CLOSE TOOLS · O</button>
        <div className="status-line">
          <Status label="DB/SCENARIO" value={scenario ? `${scenario.scenario_id}${fingerprint ? " · " + fingerprint.slice(0, 8) : ""}` : "UNAVAILABLE"} tone={scenario && !scenarioMismatch ? "ok" : "bad"} title={fingerprint ? `sha256 of GET /scenario: ${fingerprint}` : scenarioError ?? undefined} />
          <Status label="WORLD/WS" value={`${status.toUpperCase()}${snapshot ? ` · v${snapshot.world_version}` : ""}`} tone={connected ? "ok" : status === "connecting" ? "warn" : "bad"} />
          <Status label="CAMERA" value={telemetry.camera.value} tone={telemetry.camera.tone} title="Reported by the perception process via POST /perception/status" />
          <Status label="ARUCO" value={telemetry.aruco.value} tone={telemetry.aruco.tone} title={MARKER_PROVENANCE} />
          <Status label="PERCEPTRON" value={telemetry.perceptron.value} tone={telemetry.perceptron.tone} />
          <Status label="PROJECTOR" value={projectorValue} tone={projectorValue === "CALIBRATED" ? "ok" : projectorValue === "NOT OPEN" ? "bad" : "warn"} />
        </div>
        <a className="op-link" href="/projector" target="floodshift-projector">
          open /projector ↗
        </a>
      </header>

      {!liveData && (
        <div className="banner banner-bad">
          {LIVE_DATA_UNAVAILABLE} — {scenarioMismatch ? `server is not serving ${world.scenarioId}` : healthError ? `GET /health failed: ${healthError}` : scenarioError ?? `waiting for ${world.apiUrl}`}. No demo world is substituted.
        </div>
      )}
      {liveData && !connected && status !== "connecting" && (
        <div className="banner banner-bad">{CONNECTION_LOST} — the projector holds the last authoritative snapshot (v{snapshot?.world_version}). Actions will fail until the WebSocket reconnects.</div>
      )}
      {liveData && (scenario?.stage_count ?? 0) < 3 && (
        <div className="banner banner-warn">This scenario has one flood stage, activated at START. The 50-second surge will report FLOOD UPDATE UNAVAILABLE until the data owner supplies a second stage.</div>
      )}
      {!alignmentReady && <div className="banner banner-warn">ArUco: {MARKER_PROVENANCE}. Measure registration and print bounds before physical play (docs/BOARD_REGISTRATION.md).</div>}
      {!alignmentReady && <div className="banner banner-warn">{PRINT_WORLD_ALIGNMENT_NOTE}</div>}

      <main className="op-grid">
        <section className="card op-mission">
          <h2>
            Mission <small>{phase}</small>
          </h2>
          <div className="clock">
            <div className="clock-time">{inMission || finished ? `${Math.ceil(view.remainingMs / 1000)}s` : "75s"}</div>
            <div className="clock-meta">
              {clock.mode.toUpperCase()}
              {clock.sessionId && <code>{clock.sessionId}</code>}
            </div>
          </div>
          <Timeline elapsedMs={view.elapsedMs} />
          <div className="beat">
            <b>{beat.headline || "INTRO"}</b>
            <span>{beat.line}</span>
          </div>
          <div className="surge-state">
            Surge (50 s, one advance_stage): <b>{clock.surge.status}</b>
            {clock.surge.status === "failed" && <em> · {FLOOD_UPDATE_UNAVAILABLE} ({clock.surge.reason})</em>}
          </div>
          {mission.startError && <div className="error">START failed: {mission.startError}</div>}
          {mission.notice && <div className="notice">{mission.notice}</div>}

          <div className="btn-col">
            {preStart && (
              <button className="btn" onClick={() => void world.reload()}>
                LOAD LIVE SCENARIO
              </button>
            )}
            {preStart && (
              <button className="btn btn-primary" onClick={() => void mission.startGame()} disabled={!liveData || !connected || busy}>
                {mission.starting ? "STARTING…" : "START GAME"}
              </button>
            )}
            {running && (
              <button className="btn" onClick={mission.pause}>
                PAUSE
              </button>
            )}
            {paused && (
              <button className="btn btn-primary" onClick={mission.resume} disabled={!connected} title={connected ? undefined : "World connection required"}>
                RESUME
              </button>
            )}
            {running && (
              <button className="btn" onClick={() => void mission.advanceFlood()} disabled={!inputOpen}>
                ADVANCE FLOOD
              </button>
            )}
            {running && (
              <button className="btn btn-ghost" onClick={() => void mission.suggestBridge()} disabled={!inputOpen}>
                SUGGEST BRIDGE
              </button>
            )}
            {inMission && (
              <button className="btn" onClick={mission.end}>
                END &amp; SHOW RESULTS
              </button>
            )}
            {finished && (
              <button className="btn btn-primary" onClick={() => void mission.resetGame()} disabled={busy || !connected}>
                REPLAY
              </button>
            )}
            <button className="btn btn-danger" disabled={busy || !connected} onClick={() => window.confirm("RESET GAME: authoritative reset of the world, clock, pending detections and effects. Scenario data is preserved.") && void mission.resetGame()}>
              RESET GAME
            </button>
          </div>
        </section>

        <section className="card op-map" style={{ ["--board-aspect" as string]: String(scenario?.aspect_ratio ?? 1) }}>
          <h2>
            Board <small>{inputOpen ? (moving ? `click a ${PIECE_NAME[moving.type]} pad to move ${moving.id}` : `click a pad: MANUAL PLACE ${PIECE_NAME[piece]}`) : "mirror of the projector (live snapshot)"}</small>
          </h2>
          {scenario ? (
            <BoardSvg
              scenario={scenario}
              snapshot={snapshot}
              model={model}
              clock={view}
              reactions={world.reactions}
              rejections={mission.rejections}
              pending={[...world.observations.values()].filter((o) => o.vision_status === "pending")}
              surface="screen"
              variant="operator"
              results={null}
              hold={liveData ? null : LIVE_DATA_UNAVAILABLE}
              onSiteClick={inputOpen ? onSiteClick : undefined}
              highlightSite={placeSite || null}
            />
          ) : (
            <div className="map-empty">{LIVE_DATA_UNAVAILABLE}</div>
          )}
          <Legend />
        </section>

        <section className="card op-manual">
          <h2>
            Manual correction <small>same /action as the camera · logged operator_manual</small>
          </h2>
          <h3>MANUAL PLACE</h3>
          <div className="piece-row">
            {GAME_PIECES.map((p) => (
              <button key={p} className={`btn btn-piece ${piece === p ? "active" : ""}`} aria-pressed={piece === p} onClick={() => { setPiece(p); setPlaceSite(""); }}>
                <PieceIcon type={p} size={14} /> {PIECE_NAME[p]} <em>×{snapshot?.token_inventory[p] ?? "–"}</em>
              </button>
            ))}
          </div>
          <div className="form-row">
            <select aria-label="Placement site" value={placeSite} onChange={(e) => setPlaceSite(e.target.value)}>
              <option value="">choose a site for this piece…</option>
              {sitesFor(piece).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label} · {s.id}
                  {s.resource_cost != null ? ` · cost ${s.resource_cost}` : ""}
                </option>
              ))}
            </select>
            <button
              className="btn"
              disabled={!inputOpen || !placeSite}
              onClick={() => {
                const s = scenario?.sites.find((x) => x.id === placeSite);
                if (s && s.kind === TOKEN_SITE_KIND[piece]) void mission.manual.place(piece, s.id, s.board_uv);
              }}
            >
              PLACE
            </button>
          </div>

          <h3>MANUAL MOVE</h3>
          <div className="form-row">
            <select aria-label="Piece to move" value={moveToken} onChange={(e) => { setMoveToken(e.target.value); setMoveSite(""); }}>
              <option value="">choose a placed piece…</option>
              {gamePieces.map((t) => (
                <option key={t.id} value={t.id}>
                  {PIECE_NAME[t.type]} @ {t.site_id} · {t.id}
                </option>
              ))}
            </select>
            <select aria-label="Destination site" value={moveSite} onChange={(e) => setMoveSite(e.target.value)} disabled={!moving}>
              <option value="">to site…</option>
              {moving && sitesFor(moving.type).filter((s) => s.id !== moving.site_id).map((s) => <option key={s.id} value={s.id}>{s.id}</option>)}
            </select>
            <button
              className="btn"
              disabled={!inputOpen || !moving || !moveSite}
              onClick={() => {
                const s = scenario?.sites.find((x) => x.id === moveSite);
                if (s && moving) void mission.manual.move(moving.id, s.id, s.board_uv);
                setMoveSite("");
                setMoveToken("");
              }}
            >
              MOVE
            </button>
          </div>

          <h3>Pieces in the world</h3>
          <ul className="pieces">
            {gamePieces.length === 0 && <li className="muted">No response pieces accepted.</li>}
            {gamePieces.map((t) => (
              <li key={t.id}>
                <PieceIcon type={t.type} size={12} /> {PIECE_NAME[t.type]} <code>{t.site_id}</code>
                <span className={`prov prov-${t.vision_source}`}>{t.vision_source === "manual" ? "operator_manual" : t.vision_source}</span>
                <button
                  className="btn btn-sm btn-danger push-right"
                  disabled={!inputOpen}
                  onClick={() => window.confirm(`MANUAL REMOVE ${PIECE_NAME[t.type]} at ${t.site_id}? This calls remove_token on the live world.`) && void mission.manual.remove(t.id, t.board_uv)}
                >
                  MANUAL REMOVE
                </button>
              </li>
            ))}
          </ul>

          <h3>Detection</h3>
          <Detection world={world} />
          <div className="btn-row">
            <button className="btn" onClick={mission.clearPending}>
              CLEAR PENDING DETECTION
            </button>
            <button className={`btn ${debug ? "active" : ""}`} onClick={() => setDebug((v) => !v)}>
              {debug ? "HIDE DEBUG" : "SHOW DEBUG"}
            </button>
            <button
              className="btn"
              onClick={() => {
                setMuted(!muted);
                setMutedState(!muted);
              }}
            >
              {muted ? "UNMUTE" : "MUTE"}
            </button>
          </div>

          {(preStart || paused) && (
            <>
              <h3>Setup &amp; calibration</h3>
              <div className="btn-row">
                {preStart && (
                  <button className={`btn ${showCamera ? "active" : ""}`} onClick={() => setShowCamera((v) => !v)}>
                    CALIBRATE CAMERA
                  </button>
                )}
                {preStart && (
                  <button className="btn" onClick={() => mission.command("calibrate")} disabled={!projectorSeen}>
                    CALIBRATE PROJECTOR
                  </button>
                )}
                {preStart && (
                  <button className="btn" onClick={() => mission.command("test")} disabled={!projectorSeen}>
                    TEST PROJECTOR
                  </button>
                )}
                {paused && (
                  <button
                    className="btn"
                    onClick={() => {
                      setShowCamera(true);
                      mission.command("calibrate");
                    }}
                  >
                    RECALIBRATE
                  </button>
                )}
                <button className="btn btn-quiet" onClick={() => mission.command("exit-tools")} disabled={!projectorSeen}>
                  close projector tools
                </button>
              </div>
              {showCamera && <CameraCalibration world={world} />}
              {!projectorSeen && <p className="muted small">Open /projector in a second window of this browser (it links through BroadcastChannel).</p>}
            </>
          )}
        </section>

        <section className="card op-world">
          <h2>
            World <small>{snapshot ? `authoritative v${snapshot.world_version} · stage ${snapshot.simulation_stage}/${Math.max(0, (scenario?.stage_count ?? 1) - 1)} · ${snapshot.phase}` : "no snapshot"}</small>
          </h2>
          {snapshot && scenario ? <WorldPanel snapshot={snapshot} scenario={scenario} /> : <p className="muted">{LIVE_DATA_UNAVAILABLE}</p>}
        </section>

        {(finished || phase === "RESULTS") && results && (
          <section className="card op-results">
            <h2>
              Results <small role="status">{mission.resultsSyncing ? "SYNCING — waiting for action acknowledgments and the live snapshot" : `from committed snapshot v${snapshot?.world_version}`}</small>
            </h2>
            <ResultsPanel results={results} mission={mission} />
          </section>
        )}

        <section className="card op-log">
          <h2>
            Action log <small>accepted / rejected, with provenance</small>
            <button className="btn btn-sm push-right" onClick={downloadRun} disabled={!world.run.length}>
              DOWNLOAD RUN RECORD
            </button>
          </h2>
          <ol className="log">
            {world.log.map((l, i) => (
              <li key={i} className={`log-${l.kind}`}>
                <time>{l.at}</time> {l.text}
              </li>
            ))}
          </ol>
        </section>

        {debug && (
          <section className="card op-debug">
            <h2>
              Debug <small>operator only · never mirrored to the projector · keys 3–6 select a manual piece</small>
            </h2>
            <DebugPanel world={world} />
          </section>
        )}
      </main>
      <footer className="op-footer">
        Map: HOT/OSM mapped geography © OpenStreetMap contributors (ODbL) · Flood: simulated scenario hazard · Population, needs, capacity and score: educational model units, not a real-world prediction
      </footer>
    </div>
  );
}

function Timeline({ elapsedMs }: { elapsedMs: number }) {
  const marks: [string, number, number][] = [
    ["WARNING", 0, BOUNDARIES_S.CROSSING],
    ["CROSSING", BOUNDARIES_S.CROSSING, BOUNDARIES_S.RELIEF],
    ["RELIEF", BOUNDARIES_S.RELIEF, BOUNDARIES_S.SURGE],
    ["SURGE", BOUNDARIES_S.SURGE, BOUNDARIES_S.RESULTS],
    ["RESULTS", BOUNDARIES_S.RESULTS, BOUNDARIES_S.END],
  ];
  return (
    <div className="timeline">
      {marks.map(([name, a, b]) => (
        <div key={name} className="tl-seg" style={{ flex: b - a }}>
          <span>{name}</span>
        </div>
      ))}
      <div className="tl-head" style={{ left: `${(elapsedMs / MISSION_MS) * 100}%` }} />
    </div>
  );
}

function Legend() {
  return (
    <div className="legend">
      <span className="lg lg-route">reachable route</span>
      <span className="lg lg-blocked">blocked / would-be route</span>
      <span className="lg lg-danger">affected population marker</span>
      <span className="lg lg-pad">valid pad</span>
      <span className="lg lg-ghost">suggested bridge</span>
      <span className="lg lg-pending">camera candidate (pending)</span>
    </div>
  );
}

function WorldPanel({ snapshot, scenario }: { snapshot: WorldSnapshot; scenario: ScenarioGeometry }) {
  const game = snapshot.game?.status === "active" ? snapshot.game : null;
  const people = totalPeople(snapshot);
  return (
    <div className="world">
      <table className="needs">
        <thead>
          <tr>
            <th>need</th>
            <th>unmet</th>
            <th>total</th>
            <th>people reaching</th>
            <th>Δ vs no response</th>
          </tr>
        </thead>
        <tbody>
          {SERVICES.map((s) => {
            const total = totalNeed(snapshot, s);
            const key = s === "refuge" ? "people_reachable_for_shelter" : s === "medical" ? "people_reachable_for_medical" : "people_reachable_for_food";
            const delta = game?.baseline && game.current ? game.current[key] - game.baseline[key] : null;
            return (
              <tr key={s}>
                <td>{NEED_LABEL[s]}</td>
                <td className={unmetNeed(snapshot, s) > 0 ? "bad" : "ok"}>{total == null ? "–" : unmetNeed(snapshot, s)}</td>
                <td>{total ?? "–"}</td>
                <td>{people == null ? "–" : `${peopleReachable(snapshot, s)}/${people}`}</td>
                <td>{delta == null ? "–" : `${delta > 0 ? "+" : ""}${delta}`}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="world-facts">
        <span>communities reaching depot <b>{snapshot.population_demand.length ? `${snapshot.metrics.reachable_communities ?? "–"}/${snapshot.population_demand.length}` : "–"}</b></span>
        <span>blocked roads <b>{snapshot.metrics.blocked_roads}</b></span>
        <span>budget <b>{snapshot.budget_remaining_model ?? "–"}</b></span>
        <span>score <b>{game ? game.score : "–"}</b></span>
      </div>
      <table className="facilities">
        <tbody>
          {snapshot.facilities.map((f) => (
            <tr key={f.id}>
              <td>
                <PieceIcon type={f.type} size={12} /> {PIECE_NAME[f.type]} <code>{f.site_id}</code>
              </td>
              <td>
                {f.used_capacity_model}/{f.capacity_model} capacity
              </td>
              <td className={f.reachable && (f.active ?? true) ? "ok" : "bad"}>{!f.reachable ? "no supply route" : f.active === false ? "inactive" : f.used_capacity_model >= f.capacity_model ? "full" : "serving"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {snapshot.population_demand.map((d) => (
        <div key={d.id} className="pop-row">
          <code>{d.id}</code> {d.people_model} model people · depot {d.depot_reachable == null ? "unreported" : d.depot_reachable ? "reachable" : "CUT OFF"} · unmet food {d.unmet_food ?? "–"} / medical {d.unmet_medical ?? "–"} / refuge {d.unmet_refuge ?? "–"}
        </div>
      ))}
      <p className="muted small">{scenario.provenance_label}</p>
    </div>
  );
}

function ResultsPanel({ results, mission }: { results: ReturnType<typeof buildResults>; mission: Mission }) {
  return (
    <div className="results-panel">
      <div className="results-headline">{results.headline}</div>
      {mission.clock.endedEarly && <p className="muted small">Mission ended early by the operator at {Math.round(mission.view.elapsedMs / 1000)} s.</p>}
      {mission.clock.surge.status === "failed" && <p className="notice">{FLOOD_UPDATE_UNAVAILABLE}: the surge advance was rejected ({mission.clock.surge.reason}); results reflect the last accepted stage.</p>}
      {results.empty ? (
        <p className="muted">No active mission state to report.</p>
      ) : (
        <table className="results-table">
          <tbody>
            {results.rows.map((r) => (
              <tr key={r.id}>
                <td>{r.label}</td>
                <td className={r.tone === "good" ? "ok" : r.tone === "bad" ? "bad" : ""}>{r.value}</td>
                <td className="muted">{r.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {results.score && (
        <p>
          Game score <b>{results.score.value}</b> <span className="muted small">— {results.score.label}</span>
        </p>
      )}
      <div className="results-cols">
        <div>
          <h3>Improved</h3>
          {results.improved.length ? <ul>{results.improved.map((l) => <li key={l}>{l}</li>)}</ul> : <p className="muted">Nothing measured improved.</p>}
        </div>
        <div>
          <h3>Unresolved</h3>
          {results.unresolved.length ? <ul>{results.unresolved.map((l) => <li key={l}>{l}</li>)}</ul> : <p className="muted">No remaining gaps in this model.</p>}
        </div>
      </div>
    </div>
  );
}

function Detection({ world }: { world: ReturnType<typeof useLiveWorld> }) {
  const list = [...world.observations.values()];
  if (!list.length) return <p className="muted small">No camera observations on the WebSocket (vision.status). Manual placements use the same reducer.</p>;
  return (
    <ul className="obs">
      {list.map((o) => (
        <li key={o.token_id}>
          <PieceIcon type={o.object_type} size={12} /> <b>{o.object_type}</b> <code>{o.token_id}</code> <span className={`pill pill-${o.vision_status}`}>{o.vision_status === "pending" ? "CHECKING PLACEMENT" : o.vision_status}</span>
          <span className="muted small">
            {o.class_source} · uv {o.board_uv.map((n) => n.toFixed(3)).join(",")}
            {o.stable_ms != null ? ` · stable ${o.stable_ms} ms` : ""} · confidence: not in observation contract
          </span>
        </li>
      ))}
    </ul>
  );
}

function CameraCalibration({ world }: { world: ReturnType<typeof useLiveWorld> }) {
  const telemetry = perceptionView(world.perception, world.health?.perceptron_status);
  return (
    <div className="camera-cal">
      <p>
        Camera calibration runs in the lane B perception service, which reports here through <code>POST /perception/status</code>. This UI shows what it reports and never simulates a transform.
      </p>
      <ul>
        <li>camera: <b>{telemetry.camera.value}</b> · {telemetry.cameraSource ?? "source not reported"} · fps {telemetry.fps ?? "not reported"} · frame age {telemetry.frameAgeMs ?? "not reported"} ms</li>
        <li>calibration: <b>{telemetry.aruco.value}</b> · {telemetry.registrationStatus ?? "measurement status not reported"}</li>
        <li>detected marker ids: <b>{telemetry.markerIds != null ? JSON.stringify(telemetry.markerIds) : "not reported"}</b></li>
        <li>reprojection RMS: <b>{telemetry.rmsUv != null ? String(telemetry.rmsUv) + " UV" : "UV not reported"} / {telemetry.rmsPx != null ? String(telemetry.rmsPx) + " px" : "px not reported"}</b></li>
      </ul>
      {!telemetry.registrationReady && <p className="notice">Automated placement must stay blocked until the perception service reports a valid measured ArUco calibration. Its print UV still requires a reviewed transform into world UV.</p>}
    </div>
  );
}

function DebugPanel({ world }: { world: ReturnType<typeof useLiveWorld> }) {
  const p = world.perception ?? {};
  const frame = typeof p.frame_url === "string" ? p.frame_url : null;
  return (
    <div className="debug">
      <div>
        <h3>Raw camera frame</h3>
        {frame ? <img src={frame} alt="raw camera frame from the perception service" className="debug-frame" /> : <p className="muted small">No frame source reported by the perception service.</p>}
      </div>
      <div>
        <h3>Perception status (raw)</h3>
        <pre>{JSON.stringify(p, null, 2)}</pre>
        <h3>Observations</h3>
        <pre>{JSON.stringify([...world.observations.values()], null, 2)}</pre>
        <p className="small">vision latency: {world.visionLatency != null ? `${world.visionLatency} ms` : "not reported"}</p>
      </div>
      <div>
        <h3>Health</h3>
        <pre>{JSON.stringify(world.health, null, 2)}</pre>
      </div>
    </div>
  );
}
