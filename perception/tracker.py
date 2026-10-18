"""Persistent physical track IDs and the place / move / remove lifecycle (spec 6.6, 6.9, 6.10, 5).

One deterministic tracker, not three.  Association is greedy nearest-neighbour in
board millimetres with a gate; positions are smoothed over a short window; a track
only emits when it has been still for ``stable_frames`` consecutive frames.

Lifecycle (spec 5):

    new candidate ─► CANDIDATE ─(still N frames)─► emit PLACED
    PLACED/MOVED ─(drift > move gate)─► MOVING ─(still N frames at new spot)─► emit MOVED
    any emitted track ─(unmatched > occlusion grace)─► emit REMOVED, track retired
    CANDIDATE ─(unmatched > lost frames)─► LOST, track dropped (no world event)
    new track appearing where a track was just removed ─► carries previous_track_id

Legacy bugs designed out:

* **No permanent rejected-spot suppression.**  A backend rejection is recorded on the
  track; when the piece is moved and settles again the tracker emits a fresh
  PLACED (not MOVED), and an operator can also request a re-emit.  Nothing is
  blacklisted by position.
* **Move and remove exist.**  MOVED is emitted only when the adapter has bound the
  track to a world token (otherwise the "move" is a corrected placement).
* **Track IDs are not token IDs.**  The binding ``track_id -> world token`` is stored
  only so the tracker knows which lifecycle word to use, and is cleared on reset.
* **Occlusion does not age tracks** while the board registration itself is lost.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Deque

from .candidate_regions import Candidate
from .config import TrackerConfig
from .events import Appearance, ClassificationResult, Lifecycle, PieceClass


class TrackState(str, Enum):
    CANDIDATE = "candidate"   # never emitted
    STABLE = "stable"         # emitted PLACED/MOVED and currently still
    MOVING = "moving"         # emitted before, now drifting
    MISSING = "missing"       # unmatched, inside grace
    RETIRED = "retired"       # removed/lost; kept briefly for reacquisition


@dataclass
class ClassInfo:
    piece_class: PieceClass | None = None
    class_source: str | None = None
    confidence: float | None = None
    valid: bool = False
    at_ms: int | None = None
    appearance_at: Appearance | None = None
    latency_ms: int | None = None
    evidence: str | None = None
    agreement_frames: int = 0


@dataclass
class Track:
    track_id: str
    created_ms: int
    state: TrackState = TrackState.CANDIDATE
    center_mm: tuple[float, float] = (0.0, 0.0)          # smoothed
    raw_center_mm: tuple[float, float] = (0.0, 0.0)
    history_mm: Deque[tuple[float, float]] = field(default_factory=lambda: deque(maxlen=10))
    anchor_mm: tuple[float, float] | None = None        # position when the current still-streak began
    last_candidate: Candidate | None = None
    frames_observed: int = 0
    frames_stable: int = 0
    frames_missing: int = 0
    last_seen_ms: int = 0
    last_frame_id: int = 0
    emissions: int = 0                                   # per-track emission counter for event ids
    last_emitted_center_mm: tuple[float, float] | None = None
    last_emitted_lifecycle: Lifecycle | None = None
    world_token_id: str | None = None                    # set by the adapter after acceptance
    rejected_reason: str | None = None                   # last backend rejection, if any
    rejected_at_ms: int | None = None
    classification: ClassInfo = field(default_factory=ClassInfo)
    needs_classification: bool = True
    classification_reason: str = "new_track"
    classification_pending_request: str | None = None
    previous_track_id: str | None = None
    operator_note: str | None = None
    retired_at_ms: int | None = None

    @property
    def emitted(self) -> bool:
        return self.last_emitted_lifecycle in (Lifecycle.PLACED, Lifecycle.MOVED)

    @property
    def bound(self) -> bool:
        return self.world_token_id is not None

    def jitter_mm(self) -> float:
        if len(self.history_mm) < 2:
            return 0.0
        xs = [p[0] for p in self.history_mm]
        ys = [p[1] for p in self.history_mm]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        var = sum((x - mx) ** 2 + (y - my) ** 2 for x, y in zip(xs, ys)) / len(xs)
        return math.sqrt(var)

    def as_debug(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "state": self.state.value,
            "center_mm": [round(self.center_mm[0], 1), round(self.center_mm[1], 1)],
            "frames_observed": self.frames_observed,
            "frames_stable": self.frames_stable,
            "frames_missing": self.frames_missing,
            "emitted": self.last_emitted_lifecycle.value if self.last_emitted_lifecycle else None,
            "world_token_id": self.world_token_id,
            "rejected_reason": self.rejected_reason,
            "piece_class": self.classification.piece_class.value if self.classification.piece_class else None,
            "class_source": self.classification.class_source,
            "class_confidence": self.classification.confidence,
            "needs_classification": self.needs_classification,
            "previous_track_id": self.previous_track_id,
            "jitter_mm": round(self.jitter_mm(), 2),
        }


@dataclass
class TrackEvent:
    """A lifecycle transition the service turns into a PhysicalObservation."""

    track: Track
    lifecycle: Lifecycle
    emission_index: int
    frame_id: int
    at_ms: int
    center_mm: tuple[float, float]
    candidate: Candidate | None
    note: str = ""


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class PieceTracker:
    def __init__(self, cfg: TrackerConfig, *, id_prefix: str = "t"):
        self.cfg = cfg
        self.id_prefix = id_prefix
        self.tracks: dict[str, Track] = {}
        self._retired: list[Track] = []
        self._next_id = 1
        self.frame_id = 0
        self.last_update_ms = 0

    # ------------------------------------------------------------- lifecycle API
    def reset(self) -> None:
        """New session: drop tracks, bindings, retired memory and the ID counter."""
        self.tracks.clear()
        self._retired.clear()
        self._next_id = 1
        self.frame_id = 0

    def update(self, candidates: list[Candidate], now_ms: int, frame_id: int, *,
               registration_ok: bool = True) -> list[TrackEvent]:
        """Associate candidates to tracks and advance the state machine.

        ``registration_ok=False`` freezes the tracker: no ageing, no new tracks,
        no events.  Spec 5: a lost board registration must not fabricate removals.
        """
        self.frame_id = frame_id
        self.last_update_ms = now_ms
        events: list[TrackEvent] = []
        if not registration_ok:
            return events

        live = [t for t in self.tracks.values() if t.state != TrackState.RETIRED]
        pairs = []
        for ti, track in enumerate(live):
            for ci, cand in enumerate(candidates):
                d = _dist(track.center_mm, cand.center_mm)
                if d <= self.cfg.gate_mm:
                    pairs.append((d, ti, ci))
        pairs.sort()
        matched_tracks: set[int] = set()
        matched_cands: set[int] = set()
        for d, ti, ci in pairs:
            if ti in matched_tracks or ci in matched_cands:
                continue
            matched_tracks.add(ti)
            matched_cands.add(ci)
            events.extend(self._observe(live[ti], candidates[ci], now_ms, frame_id))

        for ci, cand in enumerate(candidates):
            if ci in matched_cands:
                continue
            if sum(1 for t in self.tracks.values() if t.state != TrackState.RETIRED) >= self.cfg.max_tracks:
                break
            self._spawn(cand, now_ms, frame_id)

        for ti, track in enumerate(live):
            if ti in matched_tracks:
                continue
            events.extend(self._age(track, now_ms, frame_id))

        self._purge_retired(now_ms)
        return events

    # ------------------------------------------------------------- feedback from the adapter / operator
    def bind_world_token(self, track_id: str, world_token_id: str) -> None:
        track = self.tracks.get(track_id)
        if track is not None:
            track.world_token_id = world_token_id
            track.rejected_reason = None
            track.rejected_at_ms = None

    def unbind_world_token(self, track_id: str) -> None:
        track = self.tracks.get(track_id)
        if track is not None:
            track.world_token_id = None

    def mark_rejected(self, track_id: str, reason: str, now_ms: int) -> None:
        """A backend rejection: remembered on the track, never as a blocked position."""
        track = self.tracks.get(track_id)
        if track is not None:
            track.rejected_reason = reason
            track.rejected_at_ms = now_ms
            # A rejected MOVE keeps its accepted token at the previous world site.

    def request_reemit(self, track_id: str, now_ms: int, frame_id: int, note: str = "operator_retry") -> TrackEvent | None:
        """Operator retry without touching the piece: re-emit PLACED/MOVED for a still track."""
        track = self.tracks.get(track_id)
        if track is None or track.state not in (TrackState.STABLE, TrackState.CANDIDATE):
            return None
        lifecycle = Lifecycle.MOVED if track.bound else Lifecycle.PLACED
        return self._emit(track, lifecycle, now_ms, frame_id, note)

    def clear_pending(self, track_id: str | None = None) -> int:
        """Operator CLEAR PENDING DETECTION: drop unemitted candidates (never world tokens)."""
        victims = [t for t in self.tracks.values()
                   if not t.emitted and (track_id is None or t.track_id == track_id)]
        for t in victims:
            del self.tracks[t.track_id]
        return len(victims)

    def apply_classification(self, result: ClassificationResult, now_ms: int) -> bool:
        track = self.tracks.get(result.track_id)
        if track is None:
            return False
        if result.request_id and \
                result.request_id != track.classification_pending_request:
            return False  # stale answer for an older request
        track.classification_pending_request = None
        if not result.valid:
            track.classification = ClassInfo(None, result.class_source, None, False, now_ms,
                                             track.last_candidate.appearance if track.last_candidate else None,
                                             result.latency_ms, result.evidence)
            track.needs_classification = True
            track.classification_reason = "retry_invalid_result"
            return True
        track.classification = ClassInfo(result.piece_class, result.class_source, result.confidence, True, now_ms,
                                         track.last_candidate.appearance if track.last_candidate else None,
                                         result.latency_ms, result.evidence, result.agreement_frames)
        track.needs_classification = False
        return True

    def tracks_needing_classification(self) -> list[Track]:
        return [t for t in self.tracks.values()
                if t.state in (TrackState.CANDIDATE, TrackState.STABLE)
                and t.needs_classification and t.classification_pending_request is None
                and t.frames_stable >= max(2, self.cfg.stable_frames // 3)]

    def mark_classification_requested(self, track_id: str, request_id: str) -> None:
        track = self.tracks.get(track_id)
        if track is not None:
            track.classification_pending_request = request_id

    def snapshot(self) -> list[dict[str, Any]]:
        return [t.as_debug() for t in self.tracks.values()]

    # ------------------------------------------------------------- internals
    def _spawn(self, cand: Candidate, now_ms: int, frame_id: int) -> Track:
        track = Track(track_id=f"{self.id_prefix}{self._next_id}", created_ms=now_ms)
        self._next_id += 1
        track.center_mm = cand.center_mm
        track.raw_center_mm = cand.center_mm
        track.history_mm = deque([cand.center_mm], maxlen=self.cfg.jitter_window)
        track.anchor_mm = cand.center_mm
        track.last_candidate = cand
        track.frames_observed = 1
        track.frames_stable = 0
        track.last_seen_ms = now_ms
        track.last_frame_id = frame_id
        prev = self._reacquire_source(cand.center_mm, now_ms)
        if prev is not None:
            track.previous_track_id = prev.track_id
            # Carry the class across a brief lift/replace so Dev 2 is not asked twice,
            # but flag it for re-confirmation (spec 7.6: reclassify after reacquisition).
            if prev.classification.valid:
                track.classification = ClassInfo(**{**prev.classification.__dict__})
                track.needs_classification = True
                track.classification_reason = "reacquired"
        self.tracks[track.track_id] = track
        return track

    def _reacquire_source(self, center_mm: tuple[float, float], now_ms: int) -> Track | None:
        best, best_d = None, self.cfg.reacquire_radius_mm
        for t in self._retired:
            if t.retired_at_ms is None or now_ms - t.retired_at_ms > self.cfg.reacquire_window_ms:
                continue
            d = _dist(t.center_mm, center_mm)
            if d <= best_d:
                best, best_d = t, d
        return best

    def _observe(self, track: Track, cand: Candidate, now_ms: int, frame_id: int) -> list[TrackEvent]:
        events: list[TrackEvent] = []
        track.frames_observed += 1
        track.frames_missing = 0
        track.last_seen_ms = now_ms
        track.last_frame_id = frame_id
        track.raw_center_mm = cand.center_mm
        track.history_mm.append(cand.center_mm)
        n = len(track.history_mm)
        track.center_mm = (sum(p[0] for p in track.history_mm) / n, sum(p[1] for p in track.history_mm) / n)
        previous_candidate = track.last_candidate
        track.last_candidate = cand

        if track.anchor_mm is None:
            track.anchor_mm = cand.center_mm
        drift = _dist(cand.center_mm, track.anchor_mm)
        if drift <= self.cfg.move_gate_mm:
            track.frames_stable += 1
        else:
            track.anchor_mm = cand.center_mm
            track.frames_stable = 0
            track.history_mm.clear()
            track.history_mm.append(cand.center_mm)
            track.center_mm = cand.center_mm
            if track.emitted:
                track.state = TrackState.MOVING

        if track.state == TrackState.MISSING:
            track.state = TrackState.STABLE if track.emitted else TrackState.CANDIDATE

        if previous_candidate is not None and track.classification.valid and \
                _appearance_distance(previous_candidate.appearance, cand.appearance) > self.cfg.appearance_change_threshold:
            track.needs_classification = True
            track.classification_reason = "appearance_changed"
            track.classification_pending_request = None

        if track.frames_stable >= self.cfg.stable_frames:
            if not track.emitted:
                events.append(self._emit(track, Lifecycle.PLACED, now_ms, frame_id,
                                         "re-placed after rejection" if track.rejected_reason else "placed"))
            elif track.state == TrackState.MOVING:
                moved_by = _dist(track.center_mm, track.last_emitted_center_mm or track.center_mm)
                if moved_by > self.cfg.move_gate_mm:
                    lifecycle = Lifecycle.MOVED if track.bound else Lifecycle.PLACED
                    note = "moved" if track.bound else "re-placed (not bound to a world token)"
                    events.append(self._emit(track, lifecycle, now_ms, frame_id, note))
                    track.needs_classification = track.needs_classification or not track.classification.valid
                    if track.needs_classification and track.classification_reason == "new_track":
                        track.classification_reason = "moved"
                else:
                    track.state = TrackState.STABLE  # wobbled and settled back
        return events

    def _emit(self, track: Track, lifecycle: Lifecycle, now_ms: int, frame_id: int, note: str) -> TrackEvent:
        track.emissions += 1
        track.last_emitted_center_mm = track.center_mm
        track.last_emitted_lifecycle = lifecycle
        track.state = TrackState.STABLE
        if lifecycle == Lifecycle.PLACED:
            track.rejected_reason = None
        return TrackEvent(track, lifecycle, track.emissions, frame_id, now_ms, track.center_mm,
                          track.last_candidate, note)

    def _age(self, track: Track, now_ms: int, frame_id: int) -> list[TrackEvent]:
        events: list[TrackEvent] = []
        track.frames_missing += 1
        if track.emitted:
            if track.state != TrackState.MISSING:
                track.state = TrackState.MISSING
            if track.frames_missing > self.cfg.occlusion_grace_frames:
                track.emissions += 1
                track.last_emitted_lifecycle = Lifecycle.REMOVED
                events.append(TrackEvent(track, Lifecycle.REMOVED, track.emissions, frame_id, now_ms,
                                         track.center_mm, track.last_candidate, "absent beyond occlusion grace"))
                self._retire(track, now_ms)
        else:
            if track.frames_missing > self.cfg.lost_candidate_frames:
                track.emissions += 1
                events.append(TrackEvent(track, Lifecycle.LOST, track.emissions, frame_id, now_ms,
                                         track.center_mm, track.last_candidate, "candidate vanished before stable"))
                self._retire(track, now_ms, remember=False)
        return events

    def _retire(self, track: Track, now_ms: int, remember: bool = True) -> None:
        track.state = TrackState.RETIRED
        track.retired_at_ms = now_ms
        self.tracks.pop(track.track_id, None)
        if remember:
            self._retired.append(track)

    def _purge_retired(self, now_ms: int) -> None:
        self._retired = [t for t in self._retired
                         if t.retired_at_ms is not None and now_ms - t.retired_at_ms <= self.cfg.reacquire_window_ms]


def _appearance_distance(a: Appearance, b: Appearance) -> float:
    """Normalised distance between two HSV mean/colour-fraction summaries (0..~1.7)."""
    dh = min(abs(a.mean_hsv[0] - b.mean_hsv[0]), 180 - abs(a.mean_hsv[0] - b.mean_hsv[0])) / 90.0
    ds = abs(a.mean_hsv[1] - b.mean_hsv[1]) / 255.0
    dv = abs(a.mean_hsv[2] - b.mean_hsv[2]) / 255.0
    dy = abs(a.yellow_fraction - b.yellow_fraction)
    dw = abs(a.bright_low_sat_fraction - b.bright_low_sat_fraction)
    return math.sqrt(dh * dh + ds * ds + dv * dv + dy * dy + dw * dw)
