"""Mission guide: which placements the existing rules say would help, right now.

A pure function of (bundle, state), like game.evaluate. Every option is a real
preview through reduce_action + measure, so the projector never highlights a
crossing or site that the reducer would reject or that would change nothing.
"""
from backend.simulation.reachability import measure
from backend.simulation.routing import route_edge_ids, route_geometry, route_minutes
from backend.planning.ghost_bridge import best_suggestion
from backend.world.game import NON_INTERVENTIONS, evaluate
from backend.world.rules import ALLOWED, RuleError, reduce_action

SERVICE_PIECES = ('shelter', 'hospital', 'food_shelter')
NEED_OF = {'shelter': 'refuge', 'hospital': 'medical', 'food_shelter': 'food'}
ACCESS_OF = {'refuge': 'shelter', 'medical': 'medical', 'food': 'food'}
NEEDS = ('food', 'medical', 'refuge')


def _place_name(site):
    return site.get('source_name') or site['id'].replace('_', ' ')


def _lifeline(bundle, measured, population):
    """Route from a population to the supply depot; the would-be path if it is cut."""
    nodes = {n['id']: n for n in bundle['roads']['nodes']}
    edges = measured['edges']
    result = route_minutes(edges, population['node_id'], bundle['depot_node'], nodes)
    reachable = result['reachable']
    if not reachable:
        result = route_minutes([dict(e, blocked=False) for e in edges], population['node_id'],
                               bundle['depot_node'], nodes)
        edges = [dict(e, blocked=False) for e in edges]
    if not result['reachable']:
        return None
    return {'population_id': population['id'], 'reachable': reachable,
            'edge_ids': route_edge_ids(edges, result['path']),
            'board_uv': route_geometry(edges, result['path'], nodes)}


def _preview(bundle, state, piece, site):
    action = {'type': 'place_token', 'token_type': piece, 'source': 'manual',
              'token_id': f'mission-preview:{piece}', 'site_id': site['id'], 'board_uv': site['board_uv']}
    try:
        return reduce_action(bundle, state, action), None
    except RuleError as error:
        return None, str(error)


def _baseline_view(bundle, state, population_sites):
    """The same flood stage with no response pieces: the game's own no-response baseline."""
    base = dict(state, tokens={k: t for k, t in state['tokens'].items() if t['type'] in NON_INTERVENTIONS})
    measured = measure(bundle, base)
    return {'lifelines': [line for p in measured['population_demand'] if (line := _lifeline(bundle, measured, p))],
            'populations': [{'id': p['id'], 'name': _place_name(population_sites[p['id']]),
                             'depot_reachable': p.get('depot_reachable'),
                             'unmet': {n: p.get('unmet_' + n) for n in NEEDS}} for p in measured['population_demand']],
            'blocked_edge_ids': sorted(e.get('parent_edge_id', e['id']) for e in measured['edges'] if e['blocked'])}


def mission_guide(bundle, state, measured=None, game=None):
    if state['phase'] != 'disaster_active':
        return None
    measured = measured or measure(bundle, state)
    game = game or evaluate(bundle, state, measured)
    metrics = measured['metrics']
    sites = {s['id']: s for s in bundle['sites']}
    people = measured['population_demand']
    population_sites = {p['id']: sites.get(p['id'], {}) for p in people}
    depot_site = next((s for s in bundle['sites'] if s['kind'] == 'population_node'
                       and s['node_id'] == bundle['depot_node']), None)

    def make_option(base, piece, site):
        """Preview one placement on ``base`` and report its gain against the CURRENT state."""
        preview, reason = _preview(bundle, base, piece, site)
        option = {'piece': piece, 'site_id': site['id'], 'board_uv': site['board_uv'],
                  'rotation_deg': site.get('rotation_deg'), 'edge_id': site.get('edge_id'),
                  'resource_cost': site.get('resource_cost', 0), 'allowed': preview is not None,
                  'rejection_reason': reason}
        if preview is not None:
            after = measure(bundle, preview)
            m = after['metrics']
            option.update(
                score_gain=evaluate(bundle, preview, after)['score'] - game['score'],
                communities_gain=m.get('reachable_communities', 0) - metrics.get('reachable_communities', 0),
                needs_met={n: metrics['unmet_' + n + '_model'] - m['unmet_' + n + '_model'] for n in NEEDS},
                people_reached={n: m['people_reachable_for_' + ACCESS_OF[n]] - metrics['people_reachable_for_' + ACCESS_OF[n]] for n in NEEDS},
                reconnects=[p['id'] for p in after['population_demand']
                            if p.get('depot_reachable') and not next(q for q in people if q['id'] == p['id']).get('depot_reachable')])
            option['helps'] = option['communities_gain'] > 0 or sum(option['needs_met'].values()) > 0
        return option

    occupied = {t['site_id'] for t in state['tokens'].values()}
    options = []
    for piece in ('bridge', *SERVICE_PIECES):
        if state['token_inventory'].get(piece, 0) <= 0:
            continue
        for site in sorted((s for s in bundle['sites'] if s['kind'] == ALLOWED[piece]), key=lambda s: s['id']):
            if site['id'] not in occupied:
                options.append(make_option(state, piece, site))

    helpful = [o for o in options if o['allowed'] and o['helps']]
    best = lambda items: max(items, key=lambda o: (o['score_gain'], -o['resource_cost'], o['site_id']), default=None)

    isolated = [p for p in people if p.get('depot_reachable') is False]
    lifelines = [line for p in people if (line := _lifeline(bundle, measured, p))]
    restoring_bridge = next((t for t in state['tokens'].values() if t['type'] == 'bridge' and any(
        line['reachable'] and sites[t['site_id']].get('edge_id') in line['edge_ids'] for line in lifelines)), None)
    # The crossing to restore is the existing ghost planner's answer for reconnecting people.
    suggested = best_suggestion(bundle, state, 'access') if not restoring_bridge else None
    crossing = next((o for o in helpful if o['piece'] == 'bridge' and suggested and o['site_id'] == suggested['site_id']), None)
    # A bridge placed on a crossing that reconnects no one: preview MOVING it (lift, then place).
    misplaced = None if restoring_bridge or crossing else next(
        (t for t in sorted(state['tokens'].values(), key=lambda t: t['id']) if t['type'] == 'bridge'), None)
    if misplaced:
        lifted = reduce_action(bundle, state, {'type': 'remove_token', 'source': 'manual', 'token_id': misplaced['id']})
        suggested = best_suggestion(bundle, lifted, 'access')
        if suggested and suggested['site_id'] != misplaced['site_id']:
            option = make_option(lifted, 'bridge', sites[suggested['site_id']])
            if option['allowed'] and option['helps']:
                crossing = dict(option, move_token_id=misplaced['id'])

    services = []
    for piece in SERVICE_PIECES:
        choice = best([o for o in helpful if o['piece'] == piece])
        if choice:
            services.append(choice)
    placed = [t for t in state['tokens'].values() if t['type'] in SERVICE_PIECES]

    return {
        'isolated': [{'id': p['id'], 'name': _place_name(population_sites[p['id']]), 'people_model': p['people_model']}
                     for p in isolated],
        'populations': [{'id': p['id'], 'name': _place_name(population_sites[p['id']]), 'people_model': p['people_model'],
                         'depot_reachable': p.get('depot_reachable'),
                         'unmet': {n: p.get('unmet_' + n) for n in NEEDS}} for p in people],
        'depot': {'site_id': depot_site['id'], 'name': _place_name(depot_site)} if depot_site else None,
        'lifelines': lifelines,
        'crossing': crossing,
        'crossing_restored': ({'token_id': restoring_bridge['id'], 'site_id': restoring_bridge['site_id']}
                              if restoring_bridge else None),
        'services': services,
        'services_placed': [{'token_id': t['id'], 'piece': t['type'], 'site_id': t['site_id']} for t in placed],
        'opportunity': best(helpful),
        'baseline': _baseline_view(bundle, state, population_sites),
        'stage': state['simulation_stage'],
        'stage_count': len(bundle['hazard']['stages']),
        'stage_note': (bundle['hazard'].get('stage_notes') or [None] * len(bundle['hazard']['stages']))[state['simulation_stage']],
    }
