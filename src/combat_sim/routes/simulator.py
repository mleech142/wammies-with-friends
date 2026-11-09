"""
The Simulator: its page and one attacking unit's weapons against one target.
"""

from flask import jsonify, redirect, render_template, request

from .. import access, contagion, reference
from ..app_data_edits import text_list
from ..engagement import attack_modifiers, clamp_models, leader_target, load_enhancements, load_leader, selected_rules, sources_for, target_modifiers
from ..models import Faction
from ..settings import load_settings
from ..simulation import AttackerProfile, DefenderProfile, affordable_trials, simulate_analytical, simulate_attached_analytical, simulate_monte_carlo_attached, simulate_monte_carlo_combined
from .shared import conditions_from_request


def register(app):
    """The simulator routes."""

    @app.route('/')
    def index():
        """Main simulation page (the Setup page until BSData loads or the user skips it)."""
        status = reference.current(app).bsdata_status
        if (not status.get('loaded') and not load_settings(app.config['SETTINGS_JSON']).get('setup_skipped')
                and access.is_host()):
            return redirect('/setup')
        factions = Faction.query.order_by(Faction.name).all()
        factions_list = [{'id': f.id, 'name': f.name} for f in factions]
        return render_template('index.html', factions=factions_list)
    def rules_from_keys(keys):
        """{'rule_ids', 'stratagem_ids'} from saved tick keys like 'rule:3' / 'stratagem:7'."""
        selection = {'rule_ids': [], 'stratagem_ids': []}
        for key in keys or []:
            kind, _, ident = str(key).partition(':')
            if ident.isdigit():
                (selection['rule_ids'] if kind == 'rule' else selection['stratagem_ids']).append(int(ident))
        return selection

    @app.route('/api/simulate', methods=['POST'])
    def api_simulate():
        """
        Simulate one or more weapons of one attacking unit against one target.

        Request:
        {
            "attacker": {"faction_id": 1, "weapons": [
                {"name": "Boltgun", "type": "ranged", "attacks": "2", "skill": 3, "strength": 4, "ap": 1,
                 "damage": "1", "abilities": ["Lethal Hits"], "models": 3}, ...]},
            "defender": {"toughness": 4, "save": 3, "wounds": 2, "model_count": 5, "keywords": [...], "faction_id": 2},
            "conditions": {...}, "method": "analytical" | "monte_carlo", "iterations": 1000,
            "attacker_rules": {"rule_ids": [], "stratagem_ids": []}, "target_rules": {...}
        }
        Each side can say it is "afflicted" (Death Guard's Nurgle's Gift, contagion.py: "none" for no Plague,
        or a Plague's key): an Afflicted defender has -1 Toughness, its Plague's effect applies, and attacks
        with bonuses against Afflicted units get them. "attacker" can name its "unit_id" (its datasheet's
        own abilities then count).

        "attacker" and "defender" can name a "leader_id": a leader attached to that unit, whose
        buffs apply to its side (the leader's own weapons are sent as weapons like the others). A
        defender with a leader is an attached unit: attacks go to the bodyguard models, then to the
        leader with its own profile, and the results give bodyguards_killed and leader_killed.
        A single weapon's fields directly in "attacker" (older saved scenarios) also work.

        Per-weapon rows are averages, as in Excel; the totals use the chosen method,
        with Monte Carlo rolling all the weapons together in each trial.
        """
        data = request.get_json()
        attacker_data = data['attacker']
        defender_data = data['defender']
        weapons_data = attacker_data.get('weapons') or [attacker_data]

        attacker_rules = selected_rules(data.get('attacker_rules') or rules_from_keys(attacker_data.get('rules')))
        target_rules = selected_rules(data.get('target_rules') or rules_from_keys(defender_data.get('rules')))
        conditions = conditions_from_request(data.get('conditions', {}))
        method = data.get('method', 'analytical')

        # One-off target modifiers for this defender (never saved to the datasheet)
        extra_modifiers = text_list(defender_data.get('extra_modifiers'))
        attacker_leader = load_leader(attacker_data.get('leader_id'))
        defender_leader = load_leader(defender_data.get('leader_id'))
        attacker_enhancements = load_enhancements(attacker_data.get('enhancements'))
        defender_enhancements = load_enhancements(defender_data.get('enhancements'))
        attacker_unit = load_leader(attacker_data.get('unit_id'))
        attacker_affliction = contagion.affliction(attacker_data.get('afflicted'))
        target_affliction = contagion.affliction(defender_data.get('afflicted'))
        attacker_side = sources_for(attacker_unit, attacker_leader, attacker_enhancements, attacker_rules, attacker_affliction)
        target_side = sources_for(None, defender_leader, defender_enhancements, target_rules, target_affliction)

        def target_profile(extra_keywords=()):
            return DefenderProfile(
                toughness=int(defender_data['toughness']),
                save=int(defender_data['save']),
                wounds=int(defender_data['wounds']),
                invulnerable_save=defender_data.get('invulnerable_save'),
                feel_no_pain=defender_data.get('feel_no_pain'),
                keywords=list(defender_data.get('keywords', [])) + extra_modifiers + list(extra_keywords),
                model_count=clamp_models(defender_data.get('model_count', 1))
            )

        profiles, targets, leader_targets, rows = [], [], [], []
        applied = {'attacker': [], 'target': []}
        for w in weapons_data:
            w_type = 'melee' if w.get('type') == 'melee' else 'ranged'
            # Ticked rules and stratagems add modifier text to the weapon (attacker) or the target
            attacker_modifiers = attack_modifiers(attacker_side, target_affliction, w_type, w.get('leader'),
                                                  w.get('faction_id', attacker_data.get('faction_id')))
            weapon_target_modifiers = target_modifiers(target_side, attacker_affliction, w_type, defender_data.get('faction_id'))
            for side, side_modifiers in (('attacker', attacker_modifiers), ('target', weapon_target_modifiers)):
                applied[side] += [m for m in side_modifiers if m not in applied[side]]

            skill = w.get('skill')
            profile = AttackerProfile(
                attacks=str(w['attacks']),
                skill=int(skill) if skill not in (None, '', '-') else None,
                strength=int(w['strength']),
                ap=int(w['ap']),
                damage=str(w['damage']),
                abilities=list(w.get('abilities', [])) + attacker_modifiers,
                weapon_type=w_type,
                models=clamp_models(w.get('models')),
            )
            target = target_profile(weapon_target_modifiers)
            profiles.append(profile)
            targets.append(target)
            if defender_leader is not None:
                leader_targets.append(leader_target(defender_leader, extra_modifiers + weapon_target_modifiers))

            r = simulate_analytical(profile, target, conditions)
            rows.append({
                'name': w.get('name') or w.get('weapon_name') or 'Weapon',
                'type': w_type,
                'models': profile.models,
                'attacks': r.attacks_made,
                'hits': r.hits,
                'auto_wounds': r.auto_wounds,
                'wounds': r.wounds,
                'mortal_wounds': r.mortal_wounds,
                'unsaved': r.unsaved,
                'damage_per_attack': r.damage_per_attack,
                'total_damage': r.average_damage,
                'models_killed': r.models_killed,
                'overkill': r.overkill,
            })

        if not profiles:
            return jsonify({'error': 'No weapons to simulate'}), 400

        base_target = target_profile()
        attached = None
        if defender_leader is not None:
            leader_base = leader_target(defender_leader, extra_modifiers)
            attached = {'leader': defender_leader.name, 'leader_models': leader_base.model_count,
                        'leader_wounds': leader_base.wounds * leader_base.model_count,
                        'bodyguard_models': base_target.model_count}
            combined, per_weapon = simulate_attached_analytical(profiles, base_target, leader_base, conditions,
                                                                bodyguard_targets=targets, leader_targets=leader_targets)
            for row, r in zip(rows, per_weapon):  # Each weapon in order against what is left of the unit
                row.update(attacks=r.attacks_made, hits=r.hits, auto_wounds=r.auto_wounds, wounds=r.wounds,
                           mortal_wounds=r.mortal_wounds, unsaved=r.unsaved, total_damage=r.average_damage,
                           models_killed=r.models_killed, overkill=r.overkill,
                           bodyguards_killed=r.bodyguards_killed, leader_killed=r.leader_killed,
                           leader_damage=r.leader_damage)

        if method == 'monte_carlo':
            iterations = affordable_trials(data.get('iterations', 1000), profiles, targets, conditions, 100000)
        if method == 'monte_carlo' and attached:
            result = simulate_monte_carlo_attached(profiles, base_target, leader_base, conditions, iterations,
                                                   bodyguard_targets=targets, leader_targets=leader_targets)
            summary = {
                'average_damage': result.average_damage,
                'models_killed': result.models_killed,
                'overkill': result.overkill,
                'kill_probability': result.kill_probability,
                'wipe_probability': result.wipe_probability,
                'bodyguards_killed': result.bodyguards_killed,
                'leader_killed': result.leader_killed,
                'leader_damage': result.leader_damage,
                'leader_kill_probability': result.leader_kill_probability,
            }
            breakdown = {
                'attacks': result.attacks_made,
                'hits': result.hits,
                'wounds': result.wounds,
                'failed_saves': result.failed_saves,
                'damage': result.damage_dealt,
            }
            distribution, iterations_run = result.damage_distribution, result.iterations
        elif method == 'monte_carlo':
            result = simulate_monte_carlo_combined(profiles, base_target, conditions, iterations, weapon_defenders=targets)
            summary = {
                'average_damage': result.average_damage,
                'models_killed': result.models_killed,
                'overkill': result.overkill,
                'kill_probability': result.kill_probability,
                'wipe_probability': result.wipe_probability,
            }
            breakdown = {
                'attacks': result.attacks_made,
                'hits': result.hits,
                'wounds': result.wounds,
                'failed_saves': result.failed_saves,
                'damage': result.damage_dealt,
            }
            distribution, iterations_run = result.damage_distribution, result.iterations
        else:
            total = sum(row['total_damage'] for row in rows)
            summary = {
                'average_damage': round(total, 2),
                # As in Excel: the weapons' kills add up, capped at the unit size
                'models_killed': round(min(sum(row['models_killed'] for row in rows), base_target.model_count), 2),
                'overkill': round(sum(row['overkill'] for row in rows), 2),
            }
            if attached:
                summary.update(models_killed=combined.models_killed, bodyguards_killed=combined.bodyguards_killed,
                               leader_killed=combined.leader_killed, leader_damage=combined.leader_damage)
            breakdown = {
                'attacks': round(sum(row['attacks'] for row in rows), 2),
                'hits': round(sum(row['hits'] for row in rows), 2),
                'wounds': round(sum(row['wounds'] for row in rows), 2),
                'failed_saves': round(sum(row['unsaved'] + row['mortal_wounds'] for row in rows), 2),
                'damage': round(total, 2),
            }
            distribution, iterations_run = None, 0

        return jsonify({
            'weapons': rows,
            'summary': summary,
            'breakdown': breakdown,
            'distribution': distribution,
            'method': method,
            'iterations': iterations_run,
            'applied': applied,
            'attached': attached,
        })
