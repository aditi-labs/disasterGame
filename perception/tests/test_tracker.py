from __future__ import annotations

import numpy as np
import pytest

from perception.candidate_regions import Candidate
from perception.config import TrackerConfig
from perception.events import Appearance, ClassificationResult, Lifecycle, PieceClass
from perception.tracker import PieceTracker, TrackState


def cand(x: float, y: float, *, yellow: float = 0.9) -> Candidate:
    return Candidate(center_warp_px=(x * 2, y * 2), center_mm=(x, y), contour=np.zeros((4, 1, 2), dtype=np.int32),
                     bbox_warp_px=(int(x * 2) - 70, int(y * 2) - 40, 140, 80), area_mm2=2700.0, bbox_mm=(70.0, 40.0),
                     elongation=1.75, orientation_deg=0.0, touches_board_edge=False,
                     appearance=Appearance((27.0, 180.0, 200.0), yellow, 1 - yellow), fill_ratio=0.95)


CFG = TrackerConfig(stable_frames=5, occlusion_grace_frames=4, lost_candidate_frames=3, move_gate_mm=6.0,
                    gate_mm=30.0, reacquire_window_ms=2000, reacquire_radius_mm=25.0)


def run(tracker: PieceTracker, frames: list[list[Candidate] | None], start_frame: int = 1, dt_ms: int = 33, t0: int = 0,
        registration_ok=True):
    events = []
    t = t0
    for i, cands in enumerate(frames):
        t += dt_ms
        ok = registration_ok if not callable(registration_ok) else registration_ok(i)
        events.extend(tracker.update(cands or [], t, start_frame + i, registration_ok=ok))
    return events, t


def lifecycles(events):
    return [e.lifecycle for e in events]


def test_place_then_remove():
    tr = PieceTracker(CFG)
    ev, t = run(tr, [[cand(100, 100)]] * 7)
    assert lifecycles(ev) == [Lifecycle.PLACED]
    assert ev[0].track.track_id == "t1" and ev[0].emission_index == 1
    ev2, _ = run(tr, [None] * 6, start_frame=8, t0=t)
    assert lifecycles(ev2) == [Lifecycle.REMOVED]
    assert ev2[0].track.track_id == "t1"
    assert tr.tracks == {}


def test_candidate_that_vanishes_before_stable_is_lost_not_removed():
    tr = PieceTracker(CFG)
    ev, t = run(tr, [[cand(100, 100)]] * 2 + [None] * 5)
    assert lifecycles(ev) == [Lifecycle.LOST]


def test_bound_track_emits_moved_once_when_it_settles_elsewhere():
    tr = PieceTracker(CFG)
    ev, t = run(tr, [[cand(100, 100)]] * 6)
    tr.bind_world_token("t1", "token-9")
    # drift across the board over several frames, then settle
    path = [[cand(100 + 15 * k, 100)] for k in range(1, 6)] + [[cand(175, 100)]] * 7
    ev2, _ = run(tr, path, start_frame=7, t0=t)
    assert lifecycles(ev2) == [Lifecycle.MOVED]
    assert ev2[0].track.track_id == "t1" and ev2[0].track.world_token_id == "token-9"
    assert np.allclose(ev2[0].center_mm, (175, 100), atol=1.0)


def test_unbound_track_that_moves_is_re_placed_not_moved():
    tr = PieceTracker(CFG)
    ev, t = run(tr, [[cand(100, 100)]] * 6)
    tr.mark_rejected("t1", "outside_site", t)
    ev2, _ = run(tr, [[cand(100 + 15 * k, 100)] for k in range(1, 5)] + [[cand(160, 100)]] * 7, start_frame=7, t0=t)
    assert lifecycles(ev2) == [Lifecycle.PLACED]
    assert ev2[0].emission_index == 2
    assert "re-placed" in ev2[0].note
    assert ev2[0].track.rejected_reason is None  # a fresh placement clears the old rejection


def test_rejected_spot_is_never_permanently_suppressed():
    """Legacy bug: a rejected placement blocked the position forever. Now: lift, replace, emit again."""
    tr = PieceTracker(CFG)
    ev, t = run(tr, [[cand(100, 100)]] * 6)
    tr.mark_rejected("t1", "outside_site", t)
    ev_gone, t = run(tr, [None] * 6, start_frame=7, t0=t)
    assert lifecycles(ev_gone) == [Lifecycle.REMOVED]
    ev_back, _ = run(tr, [[cand(101, 100)]] * 6, start_frame=13, t0=t)
    assert lifecycles(ev_back) == [Lifecycle.PLACED]
    assert ev_back[0].track.track_id == "t2" and ev_back[0].track.previous_track_id == "t1"


def test_wobble_within_gate_does_not_emit():
    tr = PieceTracker(CFG)
    frames = [[cand(100 + (0.5 if i % 2 else -0.5), 100)] for i in range(20)]
    ev, _ = run(tr, frames)
    assert lifecycles(ev) == [Lifecycle.PLACED]


def test_short_occlusion_inside_grace_keeps_the_track_and_emits_nothing():
    tr = PieceTracker(CFG)
    ev, t = run(tr, [[cand(100, 100)]] * 6)
    ev2, t = run(tr, [None] * 3, start_frame=7, t0=t)
    assert ev2 == [] and tr.tracks["t1"].state == TrackState.MISSING
    ev3, _ = run(tr, [[cand(100, 100)]] * 2, start_frame=10, t0=t)
    assert ev3 == [] and tr.tracks["t1"].state == TrackState.STABLE


def test_lost_registration_freezes_ageing_so_nothing_is_fabricated():
    tr = PieceTracker(CFG)
    ev, t = run(tr, [[cand(100, 100)]] * 6)
    ev2, t = run(tr, [None] * 50, start_frame=7, t0=t, registration_ok=False)
    assert ev2 == [] and "t1" in tr.tracks and tr.tracks["t1"].frames_missing == 0


def test_two_pieces_keep_distinct_ids_and_nearest_association():
    tr = PieceTracker(CFG)
    ev, t = run(tr, [[cand(100, 100), cand(300, 300)]] * 6)
    assert sorted(e.track.track_id for e in ev) == ["t1", "t2"]
    ev2, _ = run(tr, [[cand(302, 301), cand(99, 101)]] * 3, start_frame=7, t0=t)
    assert ev2 == []
    assert np.allclose(tr.tracks["t1"].center_mm, (100, 100), atol=1.5)
    assert np.allclose(tr.tracks["t2"].center_mm, (300, 300), atol=2.5)


def test_classification_is_applied_once_and_stale_requests_ignored():
    tr = PieceTracker(CFG)
    run(tr, [[cand(100, 100)]] * 3)
    need = tr.tracks_needing_classification()
    assert [t.track_id for t in need] == ["t1"]
    tr.mark_classification_requested("t1", "req-1")
    assert tr.tracks_needing_classification() == []
    stale = ClassificationResult("t1", PieceClass.HOSPITAL, "perceptron", 0.9, True, request_id="req-0")
    assert tr.apply_classification(stale, 500) is False
    good = ClassificationResult("t1", PieceClass.BRIDGE, "perceptron", 0.92, True, request_id="req-1", latency_ms=410)
    assert tr.apply_classification(good, 600) is True
    assert tr.tracks["t1"].classification.piece_class is PieceClass.BRIDGE
    assert tr.tracks_needing_classification() == []


def test_invalid_classification_never_sets_a_class_and_requests_retry():
    tr = PieceTracker(CFG)
    run(tr, [[cand(100, 100)]] * 3)
    tr.mark_classification_requested("t1", "r")
    bad = ClassificationResult("t1", None, "perceptron", None, False, request_id="r", evidence="timeout")
    assert tr.apply_classification(bad, 1)
    assert tr.tracks["t1"].classification.piece_class is None
    assert tr.tracks["t1"].needs_classification and tr.tracks["t1"].classification_reason == "retry_invalid_result"


def test_appearance_change_triggers_reclassification():
    tr = PieceTracker(CFG)
    run(tr, [[cand(100, 100, yellow=0.95)]] * 3)
    tr.mark_classification_requested("t1", "r")
    tr.apply_classification(ClassificationResult("t1", PieceClass.BRIDGE, "perceptron", 0.9, True, request_id="r"), 1)
    assert not tr.tracks["t1"].needs_classification
    run(tr, [[cand(100, 100, yellow=0.05)]] * 2, start_frame=4)
    assert tr.tracks["t1"].needs_classification and tr.tracks["t1"].classification_reason == "appearance_changed"


def test_reacquired_track_carries_class_but_asks_for_reconfirmation():
    tr = PieceTracker(CFG)
    ev, t = run(tr, [[cand(100, 100)]] * 6)
    tr.mark_classification_requested("t1", "r")
    tr.apply_classification(ClassificationResult("t1", PieceClass.BRIDGE, "perceptron", 0.9, True, request_id="r"), t)
    _, t = run(tr, [None] * 6, start_frame=7, t0=t)
    ev2, _ = run(tr, [[cand(103, 98)]] * 6, start_frame=13, t0=t)
    track = ev2[0].track
    assert track.previous_track_id == "t1"
    assert track.classification.piece_class is PieceClass.BRIDGE
    assert track.needs_classification and track.classification_reason == "reacquired"


def test_clear_pending_drops_only_unemitted_tracks():
    tr = PieceTracker(CFG)
    run(tr, [[cand(100, 100)]] * 6)
    run(tr, [[cand(100, 100), cand(300, 300)]] * 2, start_frame=7)
    assert set(tr.tracks) == {"t1", "t2"}
    assert tr.clear_pending() == 1
    assert set(tr.tracks) == {"t1"}


def test_reset_clears_everything_including_bindings_and_ids():
    tr = PieceTracker(CFG)
    run(tr, [[cand(100, 100)]] * 6)
    tr.bind_world_token("t1", "tok")
    tr.reset()
    assert tr.tracks == {} and tr._retired == []
    ev, _ = run(tr, [[cand(100, 100)]] * 6)
    assert ev[0].track.track_id == "t1" and ev[0].track.world_token_id is None and ev[0].track.previous_track_id is None


def test_operator_reemit_for_a_still_track():
    tr = PieceTracker(CFG)
    ev, t = run(tr, [[cand(100, 100)]] * 6)
    again = tr.request_reemit("t1", t + 10, 99)
    assert again is not None and again.lifecycle is Lifecycle.PLACED and again.emission_index == 2
    tr.bind_world_token("t1", "tok")
    again2 = tr.request_reemit("t1", t + 20, 100)
    assert again2.lifecycle is Lifecycle.MOVED
