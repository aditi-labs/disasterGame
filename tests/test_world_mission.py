"""Mission guidance must agree with the reducer it previews (no visual-only success)."""
from pathlib import Path

import pytest

from backend.world import WorldService
from backend.world.demo import place

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / 'scenarios/nepal_rasuwa_hot_v1'


def started():
    world = WorldService.from_bundle(BUNDLE)
    for kind, site in [('disaster_start', 'start_pad'), ('person', 'people_east'), ('person', 'people_west')]:
        assert place(world, kind, site, token_id=f'{kind}-{site}')['accepted']
    return world


def test_mission_is_absent_before_start():
    assert WorldService.from_bundle(BUNDLE).snapshot()['mission'] is None


def test_mission_crossing_is_the_one_bridge_that_reconnects_the_isolated_village():
    world = started()
    mission = world.snapshot()['mission']
    assert [p['name'] for p in mission['isolated']] == ['Shyaphru Bensi']
    assert mission['crossing']['site_id'] == 'crossing_east'
    assert mission['crossing']['reconnects'] == ['people_east']
    cut = next(line for line in mission['lifelines'] if line['population_id'] == 'people_east')
    assert not cut['reachable'] and 'crossing_east_road' in cut['edge_ids']
    before = world.snapshot()['game']['score']
    assert place(world, 'bridge', 'crossing_east')['accepted']
    after = world.snapshot()
    assert after['game']['score'] - before == mission['crossing']['score_gain']
    assert after['mission']['isolated'] == [] and after['mission']['crossing_restored']['site_id'] == 'crossing_east'
    assert next(line for line in after['mission']['lifelines'] if line['population_id'] == 'people_east')['reachable']


@pytest.mark.parametrize('site_id', ['crossing_west', 'crossing_south'])
def test_wrong_crossing_is_accepted_and_the_guide_previews_moving_it(site_id):
    world = started()
    assert world.snapshot()['mission']['crossing']['site_id'] != site_id
    assert place(world, 'bridge', site_id, token_id='b')['accepted']
    mission = world.snapshot()['mission']
    assert mission['isolated'], 'the village stays cut off'
    assert mission['crossing']['site_id'] == 'crossing_east' and mission['crossing']['move_token_id'] == 'b'
    before = world.snapshot()['game']['score']
    site = next(s for s in world.scenario()['sites'] if s['id'] == 'crossing_east')
    assert world.apply({'action_id': 'mv', 'type': 'move_token', 'source': 'manual', 'token_id': 'b',
                        'site_id': 'crossing_east', 'board_uv': site['board_uv'],
                        'expected_world_version': world.snapshot()['world_version']})['accepted']
    assert world.snapshot()['game']['score'] - before == mission['crossing']['score_gain']
    assert world.snapshot()['mission']['crossing_restored']


def test_matsyas_guidance_is_the_existing_ghost_planner():
    world = started()
    assert world.request_suggestion('access')['accepted']
    ghost = world.snapshot()['ghost_suggestion']
    assert ghost['site_id'] == world.snapshot()['mission']['crossing']['site_id'] == 'crossing_east'
    assert ghost['reason_code'] == 'reconnects_community'
    assert place(world, 'bridge', 'crossing_east')['accepted']
    assert world.snapshot()['ghost_suggestion'] is None, 'a placed bridge clears the guidance'
    assert not world.request_suggestion('access')['accepted'], 'no invented guidance once everyone is connected'


def test_baseline_view_is_the_no_response_world():
    world = started()
    assert place(world, 'bridge', 'crossing_east')['accepted']
    assert place(world, 'hospital', 'medical_site_west')['accepted']
    snap = world.snapshot()
    base = snap['mission']['baseline']
    cut = next(line for line in base['lifelines'] if line['population_id'] == 'people_east')
    assert not cut['reachable'] and 'crossing_east_road' in base['blocked_edge_ids']
    unmet = sum(v for p in base['populations'] for v in p['unmet'].values())
    assert unmet == snap['game']['baseline_unmet_total_model']


def test_every_service_option_matches_the_real_placement():
    world = started()
    assert place(world, 'bridge', 'crossing_east')['accepted']
    snapshot = world.snapshot()
    options = {o['piece']: o for o in snapshot['mission']['services']}
    assert {'shelter', 'hospital'} <= set(options)
    for piece, option in options.items():
        trial = started()
        assert place(trial, 'bridge', 'crossing_east')['accepted']
        base = trial.snapshot()
        assert place(trial, piece, option['site_id'])['accepted']
        after = trial.snapshot()
        assert after['game']['score'] - base['game']['score'] == option['score_gain']
        for need, met in option['needs_met'].items():
            assert base['metrics'][f'unmet_{need}_model'] - after['metrics'][f'unmet_{need}_model'] == met


def test_surge_cuts_the_hillside_road_and_points_to_a_remaining_response():
    world = started()
    assert place(world, 'bridge', 'crossing_east')['accepted']
    assert place(world, 'hospital', 'medical_site_west')['accepted']
    assert world.snapshot()['metrics']['people_reachable_for_medical'] > 0
    assert world.apply({'action_id': 'surge', 'type': 'advance_stage', 'source': 'manual',
                        'expected_world_version': world.snapshot()['world_version']})['accepted']
    surged = world.snapshot()
    assert surged['simulation_stage'] == 2 and surged['metrics']['people_reachable_for_medical'] == 0
    opportunity = surged['mission']['opportunity']
    assert opportunity and opportunity['allowed'] and opportunity['score_gain'] > 0
    assert place(world, opportunity['piece'], opportunity['site_id'])['accepted']
    assert world.snapshot()['game']['score'] - surged['game']['score'] == opportunity['score_gain']
