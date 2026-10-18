"""Generate UI test input with the retained reducer and the actual HOT bundle."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from backend.world.service import WorldService

world = WorldService.from_bundle(ROOT / 'scenarios/nepal_rasuwa_hot_v1')
sites = {site['id']: site for site in world.scenario()['sites']}
states = {'ready': world.snapshot()}
actions = []


def apply(kind, token_type=None, site_id=None, token_id=None):
    action = dict(action_id=f'ui-test-{len(actions)}', type=kind, source='manual',
                  expected_world_version=world.snapshot()['world_version'])
    if token_type:
        action['token_type'] = token_type
    if token_id:
        action['token_id'] = token_id
    if site_id:
        action.update(site_id=site_id, board_uv=sites[site_id]['board_uv'])
    result = world.apply(action)
    actions.append(dict(action=action, result=result))
    return result


assert apply('place_token', 'disaster_start', 'start_pad', 'start')['accepted']
for site in sites.values():
    if site['kind'] == 'population_node':
        assert apply('place_token', 'person', site['id'], site['id'])['accepted']
states['started'] = world.snapshot()
for piece, site in [('hospital', 'medical_site_west'), ('food_shelter', 'food_site_west'),
                    ('shelter', 'shelter_site_west')]:
    assert apply('place_token', piece, site, piece)['accepted']
states['services'] = world.snapshot()
assert apply('place_token', 'bridge', 'crossing_east', 'bridge')['accepted']
states['connected'] = world.snapshot()
assert apply('move_token', site_id='crossing_west', token_id='bridge')['accepted']
states['moved'] = world.snapshot()
assert apply('remove_token', token_id='bridge')['accepted']
states['removed'] = world.snapshot()
assert apply('advance_stage')['reason'] == 'last_stage'
states['failed_surge'] = world.snapshot()
assert apply('reset')['accepted']
states['reset'] = world.snapshot()
print(json.dumps(dict(scenario=world.scenario_geometry(), states=states, actions=actions)))
