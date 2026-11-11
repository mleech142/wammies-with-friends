"""
Analytics: the attackers x defenders matrix, a cell's Monte Carlo detail, Army Analysis and reverse durability.
"""

from flask import jsonify, redirect, render_template, request

from ..app_data_edits import text_list
from ..engagement import afflictions, attack_modifiers, clamp_models, enhancement_points, leader_target, load_enhancements, load_leader, selected_rules, sources_for, stat_changes, target_modifiers, unit_target, weapon_attack
from ..models import Faction, TargetProfile, Unit, db
from ..simulation import DefenderProfile, affordable_trials, simulate_analytical, simulate_attached_analytical, simulate_monte_carlo_attached, simulate_monte_carlo_combined
from ..wargear import default_used
from .shared import conditions_from_request


def weighted_average(values, weights):
    pairs = [(v, w) for v, w in zip(values, weights) if v is not None and w]
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total if total else 0.0


COVERAGE_TOUGHNESS = [3, 4, 5, 6, 8, 9, 10, 12]
COVERAGE_SAVES = [2, 3, 4, 5, 6]


def register(app):
    """The analytics routes."""

    # =========================================================================
    # Analytics (matrix comparison and Army Analysis) routes; the page was called Matchups
    # =========================================================================

    @app.route('/matchups')
    def matchups_page():
        """The page's old address."""
        return redirect('/analytics', code=301)

    @app.route('/analytics')
    def analytics_page():
        """Matrix comparison page for army analysis."""
        factions = Faction.query.order_by(Faction.name).all()
        factions_list = [{'id': f.id, 'name': f.name} for f in factions]
        # The page offers no Afflicted choices (issue #25); the API still reads "afflicted" (contagion.py)
        return render_template('analytics.html', factions=factions_list)

    # Units without a points cost count as this many points per unit (placeholder until costs are entered)
    DEFAULT_UNIT_POINTS = 1

    def load_defender(config):
        """A real unit ({'unit_id'}) or a generic target profile ({'profile_id'})."""
        if config.get('profile_id'):
            return db.session.get(TargetProfile, int(config['profile_id']))
        if config.get('unit_id'):
            return db.session.get(Unit, int(config['unit_id']))
        return None

    def combine_cells(parts, unit, model_count, points):
        """
        Matrix metrics for weapons (or units) attacking together. `parts` are
        (damage, models killed, damage lost to the cap). As in Excel, kills add up and are
        capped at the unit size; `kills_uncapped` keeps the plain sum (for "% destroyed").
        """
        damage = sum(part[0] for part in parts)
        kills = sum(part[1] for part in parts)
        return {
            'avg_damage': round(damage, 2),
            'models_killed': round(min(kills, model_count), 2),
            'kills_uncapped': round(kills, 2),
            'overkill': round(sum(part[2] for part in parts), 2),
            'damage_per_point': round(damage / points, 3) if points else round(damage, 3),
            # Rough estimate; the cell detail panel gives the simulated figure
            'kill_probability': round(min(1.0, damage / unit.wounds) * 100, 1) if unit.wounds else 0,
        }

    @app.route('/api/matrix/simulate', methods=['POST'])
    def api_matrix_simulate():
        """
        Run the attacker-unit x defender matrix.

        Request body:
        {
            "attackers": [
                {"label": "Intercessors", "unit_id": 3, "weapons": [
                    {"weapon_id": 1, "weapon_type": "ranged", "models": 9, "label": "Bolt rifle"},
                    {"weapon_id": 2, "weapon_type": "ranged", "models": 1, "label": "Plasma gun"}
                ]}
            ],
            "defenders": [
                {"unit_id": 1, "model_count": 5, "label": "Hellblasters (x5)"}
            ],
            "conditions": {"half_range": false, "charged": false, ...}
        }

        Each attacker unit's row adds up its weapons' average damage. A per-weapon
        breakdown and an "All attackers" total row are returned alongside. An attacker or
        defender can name a "leader_id": its buffs apply to that unit, and an attacker's leader
        adds its points (its weapons come in the weapons list). "afflicted": {"attackers", "defenders"}
        says either side is Afflicted (contagion.py; as in /api/simulate).
        """
        data = request.get_json()
        conditions = conditions_from_request(data.get('conditions', {}))
        attacker_affliction, defender_affliction = afflictions(data)

        # Army-wide rules and stratagems ticked for each side
        attacker_rules = selected_rules(data.get('attacker_rules'))
        defender_rules = selected_rules(data.get('defender_rules'))

        # Load attacker units and their included weapons
        attackers = []
        for atk in data.get('attackers', []):
            atk_unit = db.session.get(Unit, atk['unit_id']) if atk.get('unit_id') else None
            atk_leader = load_leader(atk.get('leader_id'))
            atk_enhancements = load_enhancements(atk.get('enhancements'))
            atk_side = sources_for(atk_unit, atk_leader, atk_enhancements, attacker_rules, attacker_affliction)
            weapons = []
            for w in atk.get('weapons', []):
                w_type = 'melee' if w.get('weapon_type') == 'melee' else 'ranged'
                weapon_modifiers = attack_modifiers(atk_side, defender_affliction, w_type, w.get('leader'),
                                                    atk_unit.faction_id if atk_unit else None)
                weapon, profile = weapon_attack(w_type, w.get('weapon_id'), w.get('models', 1), weapon_modifiers)
                if profile:
                    models = profile.models
                    weapons.append({
                        'profile': profile,
                        'label': w.get('label') or weapon.name,
                        'type': w_type,
                        'models': models,
                    })
            # Points for the chosen unit size (datasheet size if not given)
            unit_size = int(atk.get('unit_size') or (atk_unit.default_models if atk_unit else 0) or 0)
            points = atk_unit.points_for(unit_size) if atk_unit else None
            if atk_leader is not None and points is not None:
                points += atk_leader.points_for(atk_leader.default_models or 1) or 0
            if points is not None:
                points += enhancement_points(atk_enhancements)

            # Kept even if its weapons were deleted, so rows stay aligned with the request
            attackers.append({
                'label': atk.get('label') or (atk_unit.name if atk_unit else 'Unknown'),
                'points': points or DEFAULT_UNIT_POINTS,
                'weapons': weapons,
                'unit': atk_unit,
                'leader': atk_leader,
                'enhancements': atk_enhancements,
                'size': unit_size or 1,
                'stat_changes': stat_changes(atk.get('stat_changes')),
                'leader_stat_changes': stat_changes(atk.get('leader_stat_changes')),
            })

        # Load defenders
        defenders = []
        for def_config in data.get('defenders', []):
            unit = load_defender(def_config)
            if unit:
                default_models = unit.models if isinstance(unit, TargetProfile) else 1
                model_count = max(1, int(def_config.get('model_count') or default_models))
                defenders.append({
                    'unit': unit,
                    'model_count': model_count,
                    'label': def_config.get('label') or f"{unit.name} (x{model_count})",
                    'points': unit.points_for(model_count),
                    'weight': unit.weight if isinstance(unit, TargetProfile) else None,
                    # One-off target modifiers for this defender only (real units; never saved to the datasheet)
                    'extra_modifiers': text_list(def_config.get('extra_modifiers')) if isinstance(unit, Unit) else [],
                    'leader': load_leader(def_config.get('leader_id')) if isinstance(unit, Unit) else None,
                    'enhancements': load_enhancements(def_config.get('enhancements')) if isinstance(unit, Unit) else [],
                    # Its chosen wargear's characteristic changes (an army's; engagement.stat_changes)
                    'stat_changes': stat_changes(def_config.get('stat_changes')) if isinstance(unit, Unit) else None,
                    'leader_stat_changes': stat_changes(def_config.get('leader_stat_changes')) if isinstance(unit, Unit) else None,
                })

        # Each defender as seen by ranged and by melee attacks (target rules can be phase-specific);
        # with a leader it is an attached unit: its bodyguard models first, then the leader
        for d in defenders:
            d_side = sources_for(None, d['leader'], d['enhancements'], defender_rules, defender_affliction, d['extra_modifiers'])
            d_modifiers = {w_type: target_modifiers(d_side, attacker_affliction, w_type, d['unit'].faction_id)
                           for w_type in ('ranged', 'melee')}
            d['profiles'] = {w_type: unit_target(d['unit'], d['model_count'], mods, d['stat_changes'])
                             for w_type, mods in d_modifiers.items()}
            d['leader_profiles'] = {w_type: leader_target(d['leader'], mods, d['leader_stat_changes'])
                                    for w_type, mods in d_modifiers.items()} \
                if d['leader'] is not None else None
            d['total_models'] = d['model_count'] + (d['leader'].default_models or 1 if d['leader'] is not None else 0)

        def weapon_part(result):
            return (result.average_damage, result.models_killed, result.overkill)

        def cell(weapons, d, points):
            """Matrix metrics for weapons attacking a defender together (in order, for an attached unit)."""
            if d['leader_profiles'] is None:
                return combine_cells([weapon_part(simulate_analytical(w['profile'], d['profiles'][w['type']], conditions))
                                      for w in weapons], d['unit'], d['model_count'], points)
            result, _ = simulate_attached_analytical(
                [w['profile'] for w in weapons], d['profiles']['ranged'], d['leader_profiles']['ranged'], conditions,
                bodyguard_targets=[d['profiles'][w['type']] for w in weapons],
                leader_targets=[d['leader_profiles'][w['type']] for w in weapons])
            metrics = combine_cells([weapon_part(result)], d['unit'], d['total_models'], points)
            metrics.update(bodyguards_killed=result.bodyguards_killed, leader_killed=result.leader_killed,
                           leader_damage=result.leader_damage, leader_wounds=d['leader'].wounds * (d['leader'].default_models or 1))
            return metrics

        matrix = []
        weapon_matrix = []
        for atk in attackers:
            matrix.append([cell(atk['weapons'], d, atk['points']) for d in defenders])
            weapon_matrix.append([[cell([w], d, atk['points']) for d in defenders] for w in atk['weapons']])

        total_points = sum(a['points'] for a in attackers)
        all_weapons = [w for atk in attackers for w in atk['weapons']]
        total_cells = [
            cell(all_weapons, d, total_points) if d['leader_profiles'] is not None else
            combine_cells([(row[def_idx]['avg_damage'], row[def_idx]['models_killed'], row[def_idx]['overkill'])
                           for row in matrix],
                          d['unit'], d['model_count'], total_points)
            for def_idx, d in enumerate(defenders)
        ]

        results = {
            'attackers': [{
                'label': a['label'],
                'points': a['points'],
                'weapons': [{'label': w['label'], 'type': w['type'], 'models': w['models']} for w in a['weapons']],
            } for a in attackers],
            'defenders': [{'label': d['label'], 'points': d['points'], 'weight': d['weight'],
                           'leader': d['leader'].name if d['leader'] is not None else None} for d in defenders],
            'matrix': matrix,  # [attacker unit][defender]
            'weapon_matrix': weapon_matrix,  # [attacker unit][weapon][defender]
            'total': {'label': 'All attackers', 'points': total_points, 'cells': total_cells},
            'summary': {
                'best_attackers': [],  # Most efficient attacker unit for each defender
                'biggest_threats': []  # Most damaging attacker unit for each defender
            }
        }

        # Summary ranks attacker units only (not the total row)
        for def_idx, def_data in enumerate(defenders):
            if not attackers:
                break
            best = max(range(len(attackers)), key=lambda i: matrix[i][def_idx]['damage_per_point'])
            threat = max(range(len(attackers)), key=lambda i: matrix[i][def_idx]['avg_damage'])
            results['summary']['best_attackers'].append({
                'defender': def_data['label'],
                'attacker': attackers[best]['label'],
                'attacker_idx': best,
                'efficiency': matrix[best][def_idx]['damage_per_point'],
            })
            results['summary']['biggest_threats'].append({
                'defender': def_data['label'],
                'attacker': attackers[threat]['label'],
                'attacker_idx': threat,
                'damage': matrix[threat][def_idx]['avg_damage'],
            })

        # % of each target destroyed and points efficiency (Excel's kill grid and heat map)
        def add_percentages(cell, models, points):
            pct = min(1.0, cell['kills_uncapped'] / max(1, models)) * 100
            cell['pct_destroyed'] = round(pct, 1)
            cell['pct_per_100'] = round(pct / points * 100, 2) if points else None

        for atk_idx, atk in enumerate(attackers):
            for def_idx, d in enumerate(defenders):
                add_percentages(matrix[atk_idx][def_idx], d['total_models'], atk['points'])
                for weapon_cells in weapon_matrix[atk_idx]:
                    add_percentages(weapon_cells[def_idx], d['total_models'], atk['points'])
        for def_idx, d in enumerate(defenders):
            add_percentages(total_cells[def_idx], d['total_models'], total_points)
            total_cells[def_idx]['wiped'] = total_cells[def_idx]['kills_uncapped'] >= d['total_models'] - 1e-9

        results['analysis'] = army_analysis(attackers, defenders, matrix, total_cells, total_points,
                                            conditions, data.get('weapon_filter', 'both'),
                                            (attacker_affliction, defender_affliction), attacker_rules)
        return jsonify(results)

    def army_analysis(attackers, defenders, matrix, total_cells, total_points, conditions, weapon_filter,
                      afflicted=(None, None), my_rules=()):
        """Excel's Results tab: summary, gaps, role scores, T/Sv coverage and reverse durability."""
        weights = [d['weight'] if d['weight'] is not None else 1 for d in defenders]
        army_pcts = [cell['pct_destroyed'] for cell in total_cells]
        avg_pct = weighted_average(army_pcts, weights)

        # Best unit: highest weighted average % destroyed per 100 points
        best = None
        for atk_idx, atk in enumerate(attackers):
            unit_pct = weighted_average([matrix[atk_idx][i]['pct_destroyed'] for i in range(len(defenders))], weights)
            per_100 = unit_pct / atk['points'] * 100 if atk['points'] else 0
            if best is None or per_100 > best['pct_per_100']:
                best = {'label': atk['label'], 'pct_per_100': round(per_100, 2), 'avg_pct_destroyed': round(unit_pct, 1)}

        summary = {
            'units': len(attackers),
            'points': total_points,
            'targets': len(defenders),
            'wiped': sum(1 for cell in total_cells if cell.get('wiped')),
            'avg_pct_destroyed': round(avg_pct, 1),
            'pct_per_100': round(avg_pct / total_points * 100, 2) if total_points else None,
            'best_unit': best,
            'weighted': any(d['weight'] is not None for d in defenders),
        }

        # Gaps: targets the whole army can't wipe in one turn, most survivors first
        gaps = []
        for d, cell in zip(defenders, total_cells):
            if not cell.get('wiped'):
                killed = min(cell['kills_uncapped'], d['total_models'])
                gaps.append({'label': d['label'], 'models': d['total_models'],
                             'survivors': round(d['total_models'] - killed, 2), 'pct_destroyed': cell['pct_destroyed']})
        gaps.sort(key=lambda g: (-g['survivors'], g['pct_destroyed']))

        def army_kills(target):
            """Sum of each unit's kills (each capped at the target's size), uncapped across units."""
            total = 0.0
            for atk in attackers:
                unit_kills = sum(simulate_analytical(w['profile'], target, conditions).models_killed for w in atk['weapons'])
                total += min(unit_kills, target.model_count)
            return total

        # Role scores: % of each benchmark unit the army destroys (100% = wiped)
        roles = []
        for role in TargetProfile.query.filter_by(kind='role').order_by(TargetProfile.id):
            target = unit_target(role, role.models)
            kills = army_kills(target)
            roles.append({'name': role.name, 'models': role.models, 'kills': round(kills, 2),
                          'score': round(kills / max(1, role.models) * 100, 1)})

        # T/Sv coverage: expected army damage, no invulnerable/FNP/keywords, damage not capped by wounds
        coverage = []
        for toughness in COVERAGE_TOUGHNESS:
            row = []
            for save in COVERAGE_SAVES:
                target = DefenderProfile(toughness=toughness, save=save, wounds=99, model_count=1)
                row.append(round(sum(simulate_analytical(w['profile'], target, conditions).average_damage
                                     for atk in attackers for w in atk['weapons']), 2))
            coverage.append(row)

        return {
            'summary': summary,
            'gaps': gaps,
            'roles': roles,
            'coverage': {'toughness': COVERAGE_TOUGHNESS, 'saves': COVERAGE_SAVES, 'damage': coverage},
            'reverse': reverse_durability(attackers, defenders, conditions, weapon_filter, afflicted, my_rules),
        }

    def reverse_durability(attackers, defenders, conditions, weapon_filter, afflicted=(None, None), my_rules=()):
        """
        The opponent's real units attacking mine (Excel's Reverse Durability): their loadouts with the
        default ticks, quantities scaled to their model counts, same conditions, no opponent rules.
        My units defend as they would in the Simulator: with my rules', leader's and enhancements' Target
        modifiers (`my_rules`: the rules ticked for my side). `afflicted`: (my units' affliction, theirs),
        as the matrix request says (contagion.py).
        """
        mine, theirs = afflicted
        if not defenders or any(not isinstance(d['unit'], Unit) for d in defenders):
            return None  # Real units mode only

        types = {'ranged': ['ranged'], 'melee': ['melee']}.get(weapon_filter, ['ranged', 'melee'])
        enemies = []
        for d in defenders:
            unit, size = d['unit'], d['model_count']
            enemy_side = sources_for(unit, affliction=theirs)  # their datasheet's own abilities count, no rules
            scale = size / unit.default_models if unit.default_models else 1
            profiles = []
            for weapon_type in types:
                loadout = unit.loadout(weapon_type)
                for (weapon, qty), used in zip(loadout, default_used([w.name for w, _ in loadout])):
                    if used:
                        _, profile = weapon_attack(weapon_type, weapon.id, max(1, round(qty * scale)),
                                                   attack_modifiers(enemy_side, mine, weapon_type, faction_id=unit.faction_id))
                        if profile:
                            profiles.append(profile)
            enemies.append({'label': d['label'], 'profiles': profiles, 'points': d['points']})

        rows = []
        for atk in attackers:
            unit = atk['unit']
            if unit is None:
                continue
            models = atk['size'] or unit.default_models or 1
            my_side = sources_for(None, atk['leader'], atk.get('enhancements') or [], my_rules, mine)
            extra = {w_type: target_modifiers(my_side, theirs, w_type, unit.faction_id) for w_type in ('ranged', 'melee')}
            targets = {w_type: unit_target(unit, models, mods, atk['stat_changes']) for w_type, mods in extra.items()}
            leaders = {w_type: leader_target(atk['leader'], mods, atk['leader_stat_changes']) for w_type, mods in extra.items()} \
                if atk['leader'] is not None else None
            total_models = models + (leaders['ranged'].model_count if leaders else 0)
            cells = []
            for enemy in enemies:
                types = ['melee' if p.is_melee else 'ranged' for p in enemy['profiles']]
                if leaders is not None:  # My unit with its leader: bodyguard models first, then the leader
                    kills = simulate_attached_analytical(
                        enemy['profiles'], targets['ranged'], leaders['ranged'], conditions,
                        bodyguard_targets=[targets[t] for t in types],
                        leader_targets=[leaders[t] for t in types])[0].models_killed if enemy['profiles'] else 0
                else:
                    kills = sum(simulate_analytical(profile, targets[t], conditions).models_killed
                                for profile, t in zip(enemy['profiles'], types))
                cells.append(round(min(1.0, kills / total_models) * 100, 1))
            rows.append({'label': atk['label'], 'models': total_models, 'cells': cells,
                         'total': round(min(100.0, sum(cells)), 1)})

        threat = [round(sum(row['cells'][j] for row in rows), 1) for j in range(len(enemies))]
        biggest = max(range(len(enemies)), key=lambda j: threat[j]) if enemies and rows else None
        if biggest is not None and threat[biggest] <= 0:
            biggest = None  # nobody threatens anything
        points = [e['points'] for e in enemies if e['points']]
        return {
            'enemies': [e['label'] for e in enemies],
            'rows': rows,
            'summary': {
                'points': sum(points) if points else None,
                'wiped': sum(1 for row in rows if row['total'] >= 100),
                'units': len(rows),
                'avg_pct_destroyed': round(sum(row['total'] for row in rows) / len(rows), 1) if rows else 0,
                'biggest_threat': enemies[biggest]['label'] if biggest is not None else None,
            },
        }

    @app.route('/api/matrix/cell', methods=['POST'])
    def api_matrix_cell_detail():
        """
        Monte Carlo detail for one matrix cell.

        Request body:
        {
            "weapons": [{"weapon_id": 1, "weapon_type": "ranged", "models": 9}, ...],
            "unit_id": 4, "model_count": 5, "leader_id": 9,
            "conditions": {...}, "iterations": 1000
        }
        Each weapon can carry the "leader_id" of its unit's leader; the top-level one leads the defender.

        All weapons are rolled together in each iteration, so a unit row or the
        "All attackers" row gets a true combined damage distribution.
        """
        data = request.get_json()

        unit = load_defender(data)
        if unit is None:
            return jsonify({'error': 'Defender not found'}), 404
        model_count = clamp_models(data.get('model_count') or (unit.models if isinstance(unit, TargetProfile) else 1))
        attacker_rules = selected_rules(data.get('attacker_rules'))
        defender_rules = selected_rules(data.get('defender_rules'))
        extra_modifiers = text_list(data.get('extra_modifiers')) if isinstance(unit, Unit) else []
        defender_leader = load_leader(data.get('leader_id')) if isinstance(unit, Unit) else None
        defender_enhancements = load_enhancements(data.get('enhancements')) if isinstance(unit, Unit) else []
        attacker_affliction, defender_affliction = afflictions(data)
        target_side = sources_for(None, defender_leader, defender_enhancements, defender_rules, defender_affliction, extra_modifiers)
        changes = stat_changes(data.get('stat_changes')) if isinstance(unit, Unit) else None
        leader_changes = stat_changes(data.get('leader_stat_changes')) if isinstance(unit, Unit) else None

        # Each weapon with its own unit's attacker rules, against the target as its phase sees it
        profiles, targets, leader_targets = [], [], []
        for w in data.get('weapons', []):
            w_type = 'melee' if w.get('weapon_type') == 'melee' else 'ranged'
            atk_unit = db.session.get(Unit, w['unit_id']) if w.get('unit_id') else None
            atk_leader = load_leader(w.get('leader_id'))
            atk_side = sources_for(atk_unit, atk_leader, load_enhancements(w.get('enhancements')), attacker_rules,
                                   attacker_affliction)
            weapon_modifiers = attack_modifiers(atk_side, defender_affliction, w_type, w.get('leader'),
                                                atk_unit.faction_id if atk_unit else None)
            _, profile = weapon_attack(w_type, w.get('weapon_id'), w.get('models', 1), weapon_modifiers)
            if profile:
                profiles.append(profile)
                mods = target_modifiers(target_side, attacker_affliction, w_type, unit.faction_id)
                targets.append(unit_target(unit, model_count, mods, changes))
                if defender_leader is not None:
                    leader_targets.append(leader_target(defender_leader, mods, leader_changes))
        if not profiles:
            return jsonify({'error': 'No weapons found'}), 400

        conditions = conditions_from_request(data.get('conditions', {}))
        iterations = affordable_trials(data.get('iterations') or 1000, profiles, targets, conditions, 10000)
        if defender_leader is not None:  # Attached unit: bodyguard models first, then the leader
            result = simulate_monte_carlo_attached(
                profiles, unit_target(unit, model_count, extra_modifiers, changes),
                leader_target(defender_leader, extra_modifiers, leader_changes), conditions, iterations,
                bodyguard_targets=targets, leader_targets=leader_targets)
        else:
            result = simulate_monte_carlo_combined(
                profiles, unit_target(unit, model_count, extra_modifiers, changes), conditions, iterations,
                weapon_defenders=targets,
            )

        return jsonify({
            'summary': {
                'average_damage': result.average_damage,
                'models_killed': result.models_killed,
                'overkill': result.overkill,
                'kill_probability': result.kill_probability,
                'wipe_probability': result.wipe_probability,
                'bodyguards_killed': result.bodyguards_killed,
                'leader_killed': result.leader_killed,
                'leader_damage': result.leader_damage,
                'leader_kill_probability': result.leader_kill_probability,
            },
            'breakdown': {
                'attacks': result.attacks_made,
                'hits': result.hits,
                'wounds': result.wounds,
                'failed_saves': result.failed_saves,
                'damage': result.damage_dealt,
            },
            'distribution': result.damage_distribution,
            'method': result.method,
            'iterations': result.iterations,
        })
