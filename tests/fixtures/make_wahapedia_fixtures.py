"""
Writes the made-up Wahapedia export the tests run on: invented factions, datasheets, rules and stratagems in the
format of the real files. Run it after changing a fixture:

    python tests/fixtures/make_wahapedia_fixtures.py

Two folders:

- tests/fixtures/wahapedia (WAHAPEDIA_FIXTURES): the whole export, units with rules and stratagems;
- tests/fixtures/wahapedia_units (UNIT_FIXTURES): the same without Stratagems.csv, so its rules and stratagems
  aren't imported (wahapedia.load_folder needs that file) and tests see only the units, as the app does before
  its rules are downloaded.

The real format: '|'-separated, a header row, every row ending in '|', UTF-8 with a byte order mark, HTML in text
fields, and line breaks inside fields without quoting (the Bastion's legend). IDs are the export's own: any text
(the real export's are numbers); these keep the names the tests use ('u-void', 'd-vanguard', 'enh-sights').
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / 'wahapedia'
UNITS_OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / 'wahapedia_units'


def strat(when, target, effect):
    return f'<b>WHEN:</b> {when}<br><br><b>TARGET:</b> {target}<br><br><b>EFFECT:</b> {effect}'


def kw(*words):
    return ' '.join(f'<span class="kwb">{w.upper()}</span>' for w in words)


ONE_UNIT = f'One {kw("Starfarers")} unit from your army.'
CAPTAIN_TEXT = ('While this model is leading a unit, ranged weapons equipped by models in that unit have the '
                '[LETHAL HITS] ability. In addition, each time an attack targets that unit, subtract 1 from the Hit '
                'roll. You can re-roll Charge rolls made for that unit.')

# --- Rules and stratagems ----------------------------------------------------------------------

RULES = {
    'Last_update': (['last_update'], [['2026-10-01 12:00:00']]),
    'Factions': (['id', 'name', 'link'], [
        ['SF', 'Starfarers', 'https://example.invalid/starfarers'],
        ['AL', 'Allies', 'https://example.invalid/allies'],
        ['NF', 'Neutral Forces', 'https://example.invalid/neutral'],
        ['GL', 'Ghost Legion', 'https://example.invalid/ghost-legion'],
        ['XX', 'Empty Stub', 'https://example.invalid/empty'],  # No datasheets: not imported as a faction
    ]),
    'Detachments': (['id', 'faction_id', 'name', 'legend', 'type', 'dp', 'force_disposition'], [
        ['d-vanguard', 'SF', 'Void Vanguard', '', '', '2', 'Purge the Foe'],
        ['d-bastion', 'SF', 'Star Bastion', '', '', '1', 'Take and Hold'],
        ['d-citadel', 'SF', 'Star Citadel', '', '', '1', 'Take and Hold'],
        ['d-armada', 'SF', 'Star Armada', '', '', '3', 'Priority Assets'],
        ['d-lost', 'SF', 'Lost Fleet', '', '', '1', ''],
        ['d-task-force', 'AL', 'Allied Task Force', '', '', '2', 'Disruption'],
        ['d-breach', 'SF', 'Hull Breach', '', 'Boarding Actions', '', ''],  # Another way of playing: left out
    ]),
    'Stratagems': (['faction_id', 'name', 'id', 'type', 'cp_cost', 'legend', 'turn', 'phase', 'detachment',
                    'detachment_id', 'description'], [
        ['SF', 'VOID STRIKE', '101', 'Void Vanguard – Battle Tactic Stratagem', '1', '', 'Your turn', 'Shooting phase',
         'Void Vanguard', 'd-vanguard', strat('Your Shooting phase.', ONE_UNIT,
                                              'Until the end of the phase, ranged weapons equipped by models in your '
                                              'unit have the [LETHAL HITS] ability.')],
        ['SF', 'BASTION OF STARS', '102', 'Star Bastion – Battle Tactic Stratagem', '1', 'The walls hold.\nThey always hold.',
         'Opponent’s turn', 'Shooting or Fight phase', 'Star Bastion', 'd-bastion',
         strat('Your opponent’s Shooting phase or the Fight phase, just after an enemy unit has selected its targets.',
               ONE_UNIT, 'Until the end of the phase, each time an attack targets your unit, subtract 1 from the Wound roll.')],
        ['SF', 'REDEPLOY', '103', 'Void Vanguard – Strategic Ploy Stratagem', '2', '', 'Your turn', 'Movement phase',
         'Void Vanguard', 'd-vanguard', strat('Your Movement phase.', ONE_UNIT,
                                              'Remove your unit from the battlefield and place it into Strategic Reserves.')],
        ['SF', 'LOST SIGNAL', '104', 'Lost Fleet – Battle Tactic Stratagem', '1', '', 'Your turn', 'Shooting phase',
         'Lost Fleet', 'd-lost', strat('Your Shooting phase.', ONE_UNIT, "Your unit's ranged attacks have [PRECISION].")],
        ['AL', 'COMBINED ARMS', '105', 'Allied Task Force – Battle Tactic Stratagem', '1', '', 'Your turn', 'Fight phase',
         'Allied Task Force', 'd-task-force', strat('Your Fight phase.', 'One unit from your army.',
                                                    'If your unit is within range of an objective marker, your unit’s '
                                                    'melee attacks have [LANCE] and +1 AP.')],
        ['', 'COMMAND RE-ROLL', '201', 'Core Stratagem', '1', '', 'Either player’s turn', 'Any phase', '', '',
         strat('Any phase, just after you have made a Hit roll.', 'That unit or model from your army.',
               'You re-roll that roll, test or saving throw.')],
        ['', 'SMOKESCREEN', '202', 'Core Stratagem', '1', '', 'Opponent’s turn', 'Shooting phase', '', '',
         strat('Your opponent’s Shooting phase, just after an enemy unit has selected its targets.',
               f'One {kw("Smoke")} unit from your army.',
               'Until the end of the phase, models in your unit have the Stealth ability.<ul><li>Smoke rises.</li></ul>')],
        ['', 'NORMAL MOVE', '203', 'Movement Ability', '', '', 'Your turn', 'Movement phase', '', '',
         'Move each model up to its Move characteristic.'],
        # Left out: an older core set, a mission pack's card, and an older stratagem of the same name
        ['', 'GO TO GROUND', '204', 'Core – Wargear Stratagem', '1', '', 'Opponent’s turn', 'Shooting phase', '', '',
         strat('Your opponent’s Shooting phase.', 'One unit from your army.', 'Your unit has 6+ InSv.')],
        ['', 'ALL IN', '205', 'Challenger – Strategic Ploy Stratagem', '1', '', 'Your turn', 'Command phase', '', '',
         strat('Your Command phase.', 'Your army.', 'Gain 1CP.')],
        ['', 'SMOKESCREEN', '199', 'Core Stratagem', '2', '', 'Opponent’s turn', 'Shooting phase', '', '',
         strat('Your opponent’s Shooting phase.', 'One unit from your army.', 'Your unit has 6+ InSv.')],
    ]),
    'Detachment_abilities': (['id', 'faction_id', 'name', 'legend', 'description', 'detachment', 'detachment_id'], [
        ['301', 'SF', 'Vanguard Doctrine', '', '<b>Doctrine:</b> Each time a model in your unit makes a melee attack, '
         'add 1 to the Hit roll.', 'Void Vanguard', 'd-vanguard'],
        ['302', 'SF', 'Lost Doctrine', '', 'Models in your unit have the Stealth ability.', 'Lost Fleet', 'd-lost'],
        ['303', 'SF', 'Hold Fast', '', 'Units on objectives get +1 to their saves.', 'Star Bastion', 'd-bastion'],
        ['304', 'SF', 'Walls', '', 'Units in cover get +1 to their saves.', 'Star Citadel', 'd-citadel'],
        ['305', 'SF', 'Fleet', '', 'The whole fleet strikes.', 'Star Armada', 'd-armada'],
        ['306', 'AL', 'Assigned', '', 'Agents can join any army.', 'Allied Task Force', 'd-task-force'],
    ]),
    'Abilities': (['id', 'name', 'legend', 'faction_id', 'description'], [
        ['401', 'Star Oath', '', 'SF', 'Each time a model in your unit makes an attack, re-roll a Hit roll of 1.'],
        ['402', 'Super-heavy Walker', '', 'SF', 'This model can move over other models.'],  # Also a core ability
        ['403', 'Deep Strike', '', '', 'This unit can be set up in Reserves.'],
        ['404', 'Ghostly', '', 'GL', 'Models in your unit have a 4+ invulnerable save.'],
        ['405', 'Star Lore', '', 'SF', 'Not an army rule: only on a datasheet.'],
        ['406', 'Feel No Pain', '', '', 'Ignore wounds on a roll.'],
        ['407', 'Stealth', '', '', 'Hard to hit at range.'],
        ['408', 'Leader', '', '', 'Can lead a unit.'],
        ['409', 'Star Pact', '', 'SF', 'Each time a unit from this army is selected to shoot, it can re-roll one Hit roll.'],
    ]),
}

# --- Datasheets ----------------------------------------------------------------------------------
# A datasheet: (id, name, faction, source, role, loadout, flags), its stat lines, composition, costs, weapons,
# options, keywords and abilities. Flags: 'virtual', 'support'.

SHEETS = [
    dict(id='u-agent', name='Ally Agent', faction='AL', role='Characters',
         loadout='<b>This model is equipped with:</b> laser pistol.',
         models=[('Ally Agent', '6"', '3', '4+', '', '', '3', '6+', '1', '')],
         composition=['1 Ally Agent'], costs=[('YOUR UNIT COSTS', ''), ('1 model', '50')],
         weapons=[('Laser pistol', 'Pistol', '12', 'Ranged', '1', '3', '4', '-1', '1')], keywords=['Infantry']),
    dict(id='u-troupe', name='Wandering Troupe', faction='AL', role='Other', loadout='',
         models=[('Wanderer', '8"', '3', '6+', '', '', '1', '7+', '1', '')],
         composition=['5 Wanderers'], costs=[('YOUR UNIT COSTS', ''), ('5 models', '80')], keywords=['Infantry']),
    dict(id='u-wall', name='Neutral Wall', faction='NF', role='Fortification', loadout='',
         models=[('Neutral Wall', '-', '9', '4+', '', '', '12', '-', '0', '')],
         composition=['1 Neutral Wall'], costs=[('YOUR UNIT COSTS', ''), ('1 model', '40')], keywords=['Vehicle']),
    dict(id='u-beasts', name='Beast Pack', faction='SF', role='Other',
         loadout='<b>The Beastmaster is equipped with:</b> close combat weapon.<br><br>'
                 '<b>Every Beast is equipped with:</b> claws.',
         models=[('Beastmaster', '10"', '5', '6+', '', '', '2', '8+', '0', '75 x 42mm'),
                 ('Beast', '10"', '5', '6+', '', '', '2', '8+', '0', '75 x 42mm')],
         composition=['1 Beastmaster and 3 Beasts'], costs=[('YOUR UNIT COSTS', ''), ('4 models', '60')],
         weapons=[('Close combat weapon', '', 'Melee', 'Melee', '1', '4', '4', '0', '1'),
                  ('Claws', '', 'Melee', 'Melee', '3', '4', '5', '-1', '1')],
         options=['The Beastmaster’s close combat weapon can be replaced with 1 power axe.'], keywords=['Infantry']),
    dict(id='u-bunker', name='Field Bunker', faction='SF', role='Fortification', loadout='',
         models=[('Field Bunker', '-', '10', '3+', '', '', '15', '-', '0', '')],
         composition=['1 Field Bunker'], costs=[('YOUR UNIT COSTS', ''), ('1 model', '100')], keywords=['Vehicle'],
         abilities=[('402', '', '', 'Core', ''), ('403', '', '', 'Core', '')]),
    dict(id='u-medic', name='Field Medic', faction='SF', role='Characters', flags=('support',),
         loadout='<b>This model is equipped with:</b> medic pistol.',
         models=[('Field Medic', '6"', '4', '4+', '4', '* Against melee attacks only', '3', '6+', '1', '')],
         composition=['1 Field Medic'], costs=[('YOUR UNIT COSTS', ''), ('1 model', '40')],
         weapons=[('Medic pistol', 'Pistol', '12', 'Ranged', '1', '4', '3', '0', '1')], keywords=['Infantry', 'Support']),
    dict(id='u-crew', name='Gun Crew', faction='SF', role='Other',
         loadout='<b>Every model is equipped with:</b> crew gun.',
         models=[('Gunner', '5"', '3', '5+', '', '', '1', '7+', '1', '')],
         composition=['2-4 Gunners'],
         costs=[('YOUR UNIT COSTS', ''), ('2 models', '65'), ('3 models', '80'), ('4 models', '150')],
         weapons=[('Crew gun', '', '36', 'Ranged', '2', '4', '8', '-2', '3')], keywords=['Infantry']),
    dict(id='u-drone', name='Scout Drone', faction='SF', role='Other',
         loadout='<b>This model is equipped with:</b> drone gun.',
         models=[('Scout Drone', '12"', '4', '4+', '', '', '3', '8+', '0', '')],
         composition=['1 Scout Drone'], costs=[('YOUR UNIT COSTS', ''), ('1 model', '30')],
         weapons=[('Drone gun', 'Assault', '18', 'Ranged', '3', '4', '4', '0', '1')], keywords=['Vehicle'],
         abilities=[('', 'Flicker Field', 'Each time an attack is allocated to this model, subtract 1 from the Damage '
                     'characteristic of that attack.', 'Datasheet', '')]),
    dict(id='u-brutes', name='Shield Brutes', faction='SF', role='Other',
         loadout='<b>Every model is equipped with:</b> brute club.',
         models=[('Shield Brute', '6"', '6', '3+', '', '', '4', '7+', '1', '50mm')],
         composition=['3 Shield Brutes'],
         costs=[('YOUR UNIT COSTS', ''), ('3 models', '90'), ('WARGEAR OPTIONS', ''), ('per Brute shield', '10')],
         weapons=[('Brute club', '', 'Melee', 'Melee', '4', '3', '7', '-1', '2')], keywords=['Infantry'],
         options=['Any number of models can each be equipped with 1 brute shield.'],  # Not a weapon: priced all the same
         abilities=[('', 'Brute Roar', 'This unit shouts.', 'Datasheet', ''),
                    ('', 'Bastion Drill', 'This unit is eligible to shoot in a turn in which it Fell Back.',
                     'Datasheet', '')]),
    dict(id='u-captain', name='Star Captain', faction='SF', role='Characters',
         loadout='<b>This model is equipped with:</b> master blade.',
         models=[('Star Captain', '6"', '4', '2+', '4', '', '5', '6+', '1', '')],
         composition=['1 Star Captain'], costs=[('YOUR UNIT COSTS', ''), ('1 model', '70'),
                                                 ('YOUR UNIT COSTS', ''), ('1 model', '70')],  # Repeated, as the export does
         weapons=[('Master blade', 'Sustained Hits 1', 'Melee', 'Melee', '5', '2', '6', '-2', '2'),
                  ('Plasma pistol', 'Pistol', '12', 'Ranged', '1', '3', '7', '-2', '1')],
         options=['This model can be equipped with 1 plasma pistol.'], keywords=['Infantry', 'Character'],
         abilities=[('408', '', '', 'Core', ''), ('409', '', '', 'Faction', ''),
                    ('', 'Iron Will', 'This model has the Feel No Pain 5+ ability.', 'Datasheet', ''),
                    ('', 'Captain’s Command', CAPTAIN_TEXT, 'Datasheet', '')]),
    dict(id='u-herald', name='Star Herald', faction='SF', role='Characters',
         loadout='<b>This model is equipped with:</b> herald staff.',
         models=[('Star Herald', '10"', '5', '4+', '', '', '5', '6+', '1', '')],
         composition=['1 Star Herald'], costs=[('YOUR UNIT COSTS', ''), ('1 model', '60')],
         weapons=[('Herald staff', '', 'Melee', 'Melee', '3', '3', '5', '-1', '2')], keywords=['Character']),
    dict(id='u-lord', name='Star Lord', faction='SF', role='Characters',
         loadout='<b>This model is equipped with:</b> star sword.',
         models=[('Star Lord', '6"', '5', '2+', '4', '', '6', '5+', '2', '')],
         composition=[f'1 Star Lord – {kw("Epic", "Hero")}'], costs=[('YOUR UNIT COSTS', ''), ('1 model', '120')],
         weapons=[('Star sword', '', 'Melee', 'Melee', '6', '2', '7', '-3', '2')],
         keywords=['Character', 'Epic Hero'], abilities=[('408', '', '', 'Core', '')]),
    dict(id='u-walker', name='Star Walker', faction='SF', source='501', role='Vehicle',
         loadout='<b>This model is equipped with:</b> walker flamer; armoured feet.',
         models=[('Star Walker', '8"', '9', '3+', '', '', '10', '7+', '3', 'Use model')],
         composition=['1 Star Walker'],
         costs=[('YOUR UNIT COSTS', ''), ('1 model', '120'), ('WARGEAR OPTIONS', ''), ('per Walker flamer', '10')],
         weapons=[('Walker flamer', 'Ignores Cover, Torrent, Twin-linked', '12', 'Ranged', 'D6', 'N/A', '5', '-1', '1'),
                  ('Armoured feet', '', 'Melee', 'Melee', '4', '4', '7', '0', '1'),
                  ('Broken gun', '', '24', 'Ranged', '1', '4', 'User', '0', '1')],  # Unreadable S: left out
         options=['This model can be equipped with 1 more walker flamer.'], keywords=['Vehicle'],
         abilities=[('406', '', '', 'Core', '6+'), ('403', '', '', 'Core', ''), ('401', '', '', 'Faction', ''),
                    ('402', '', '', 'Faction', ''),
                    ('', 'Stride Protocol', 'This model can Advance 6".', 'Datasheet', '')]),
    dict(id='u-void', name='Void Warriors', faction='SF', role='Battleline',
         loadout='<b>The Void Sergeant is equipped with:</b> laser pistol; blade.<br><br>'
                 '<b>Every Void Warrior is equipped with:</b> laser rifle; close combat weapon.',
         models=[('Void Sergeant', '6"', '4', '3+', '', '', '3', '6+', '2', '32mm'),
                 ('Void Warrior', '6"', '4', '3+', '', '', '2', '6+', '2', '32mm')],
         composition=['1 Void Sergeant and 4 Void Warriors', 'OR', '1 Void Sergeant and 9 Void Warriors'],
         costs=[('YOUR 1ST TO 2ND UNITS COST', ''), ('5 models', '80'), ('10 models', '160'),
                ('YOUR 3RD+ UNIT COSTS', ''), ('5 models', '90'), ('10 models', '170'),
                ('WARGEAR OPTIONS', ''), ('per Heavy laser', '5')],
         weapons=[('Laser pistol', 'Pistol', '12', 'Ranged', '1', '3', '4', '-1', '1'),
                  ('Laser rifle - standard', 'Rapid Fire 1', '24', 'Ranged', '2', '3', '4', '0', '1'),
                  ('Laser rifle - overcharge', 'Hazardous', '24', 'Ranged', '2', '3', '7', '-2', '2'),
                  ('Heavy laser', 'Heavy, Anti-vehicle 4+, Laser Burn', '36', 'Ranged', '1', '4', '9', '-3', 'D6'),
                  ('Blade', 'Lethal Hits', 'Melee', 'Melee', '3', '3', '5', '-1', '1'),
                  ('Close combat weapon', '', 'Melee', 'Melee', '1', '4', '4', '0', '1'),
                  ('Power axe', '', 'Melee', 'Melee', '3', '3', '6', '-2', '1')],
         options=['For every 5 models in this unit, 1 Void Warrior’s laser rifle can be replaced with 1 heavy laser.',
                  'The Void Sergeant’s blade can be replaced with 1 power axe.'],
         keywords=['Infantry', 'Battleline'],
         abilities=[('407', '', '', 'Core', ''), ('409', '', '', 'Faction', ''),
                    ('', 'Shield Wall', 'Models in this unit can do things.', 'Datasheet', ''),
                    ('', 'Void Shield', 'This model has a 5+ invulnerable save.', 'Wargear', '')]),
    dict(id='u-marksmen', name='Void Marksmen', faction='SF', role='Infantry',
         loadout='<b>Every model is equipped with:</b> marksman rifle; close combat weapon.',
         models=[('Void Marksman', '6"', '3', '5+', '5', '* Against ranged attacks only', '1', '7+', '1', '28.5mm')],
         composition=['3-6 Void Marksman models'], costs=[('YOUR UNIT COSTS', ''), ('3 models', '45'), ('6 models', '90')],
         weapons=[('Marksman rifle', 'Heavy, Precision', '36', 'Ranged', '1', '3', '5', '-1', '2'),
                  ('Close combat weapon', '', 'Melee', 'Melee', '1', '4', '4', '0', '1')],
         keywords=['Infantry']),
    dict(id='u-echo', name='Summoned Echo', faction='SF', role='Other', flags=('virtual',), loadout='',
         models=[('Summoned Echo', '-', '1', '7+', '', '', '1', '-', '0', '')], composition=[], costs=[]),
    dict(id='u-spectre', name='Spectre', faction='GL', role='Infantry',
         loadout='<b>This model is equipped with:</b> spectral touch.',
         models=[('Spectre', '8"', '3', '6+', '4', '', '1', '7+', '1', '25mm')],
         composition=['1 Spectre'], costs=[('YOUR UNIT COSTS', ''), ('1 model', '20')],
         weapons=[('Spectral touch', '', 'Melee', 'Melee', '2', '4', '3', '0', '1')], keywords=['Infantry'],
         abilities=[('404', '', '', 'Faction', ''), ('405', '', '', 'Datasheet', ''),
                    ('', 'Ethereal', 'This model has the Feel No Pain 5+ ability.', 'Datasheet', '')]),
]

FACTION_KEYWORD = {'SF': 'Starfarers', 'AL': 'Allies', 'NF': 'Neutral Forces', 'GL': 'Ghost Legion'}
LEADERS = [('u-captain', 'u-void'), ('u-lord', 'u-void'), ('u-medic', 'u-void'), ('u-medic', 'u-crew')]

ENHANCEMENTS = [  # (faction, name, id, cost, detachment, detachment id, upgrade, text, datasheets)
    ('SF', 'Targeting Sights', 'enh-sights', '10', 'Void Vanguard', 'd-vanguard', 'true',
     'Gun Crew unit only. This unit’s ranged attacks have [IGNORES COVER].', ['u-crew']),
    ('SF', 'Void Blade', 'enh-void-blade', '20', 'Void Vanguard', 'd-vanguard', 'false',
     f'{kw("Starfarers")} model only. This model’s melee attacks have [LETHAL HITS].',
     ['u-captain', 'u-herald']),  # Not the Star Lord: an Epic Hero
    ('SF', 'Bastion Ward', 'enh-bastion-ward', '15', 'Star Bastion', 'd-bastion', 'false',
     'While the bearer is leading a unit, models in that unit have a 4+ invulnerable save.', ['u-captain', 'u-lord']),
    ('SF', 'Armada Relic', 'enh-armada-relic', '30', 'Star Armada', 'd-armada', 'false',
     'Once per battle, the bearer can do something clever.', ['u-captain', 'u-herald', 'u-lord']),
    ('SF', 'Sun Crown', 'enh-sun-crown', '25', 'Void Vanguard', 'd-vanguard', 'false', 'The bearer shines.',
     ['u-herald']),
    ('SF', 'Line Banner', 'enh-line-banner', '10', 'Void Vanguard', 'd-vanguard', 'true',
     'This unit’s attacks have +1 S.', ['u-crew', 'u-void']),  # An Upgrade for several datasheets
    ('SF', 'Boarding Hook', 'enh-hook', '5', 'Hull Breach', 'd-breach', 'false', 'For boarding actions only.',
     ['u-captain']),
]


def datasheet_tables():
    t = {
        'Source': (['id', 'name', 'type', 'edition', 'version', 'errata_date', 'errata_link'], [
            ['500', 'Codex: Starfarers', 'Codex', '11', '1.0', '', ''],
            ['501', 'Starfarers (Warhammer Legends)', 'Faction Pack', '11', '', '', ''],
        ]),
        'Datasheets': (['id', 'name', 'faction_id', 'source_id', 'legend', 'role', 'loadout', 'transport', 'virtual',
                        'is_support', 'leader_head', 'leader_footer', 'damaged_w', 'damaged_description', 'link'], []),
        'Datasheets_models': (['datasheet_id', 'line', 'name', 'M', 'T', 'Sv', 'inv_sv', 'inv_sv_descr', 'W', 'Ld',
                               'OC', 'base_size', 'base_size_descr'], []),
        'Datasheets_unit_composition': (['datasheet_id', 'line', 'description'], []),
        'Datasheets_models_cost': (['datasheet_id', 'line', 'description', 'cost'], []),
        'Datasheets_wargear': (['datasheet_id', 'line', 'line_in_wargear', 'dice', 'name', 'description', 'range',
                                'type', 'A', 'BS_WS', 'S', 'AP', 'D'], []),
        'Datasheets_options': (['datasheet_id', 'line', 'button', 'description'], []),
        'Datasheets_keywords': (['datasheet_id', 'keyword', 'model', 'is_faction_keyword'], []),
        'Datasheets_abilities': (['datasheet_id', 'line', 'ability_id', 'model', 'name', 'description', 'type',
                                  'parameter'], []),
        'Datasheets_leader': (['leader_id', 'attached_id'], [list(pair) for pair in LEADERS]),
        'Enhancements': (['faction_id', 'name', 'id', 'cost', 'detachment', 'detachment_id', 'upgrade', 'legend',
                          'description', 'support_leader'], []),
        'Datasheets_enhancements': (['datasheet_id', 'enhancement_id'], []),
    }
    for s in SHEETS:
        flags = s.get('flags', ())
        t['Datasheets'][1].append([s['id'], s['name'], s['faction'], s.get('source', '500'), '', s['role'],
                                   s['loadout'], '', 'true' if 'virtual' in flags else 'false',
                                   'true' if 'support' in flags else 'false', '', '', '', '', ''])
        for i, m in enumerate(s['models'], 1):
            t['Datasheets_models'][1].append([s['id'], str(i), *m[:9], m[9], ''])
        for i, line in enumerate(s['composition'], 1):
            t['Datasheets_unit_composition'][1].append([s['id'], str(i), line])
        for i, (text, cost) in enumerate(s['costs'], 1):
            t['Datasheets_models_cost'][1].append([s['id'], str(i), text, cost])
        for i, w in enumerate(s.get('weapons', []), 1):
            name, abilities, range_, kind, a, skill, strength, ap, damage = w
            t['Datasheets_wargear'][1].append([s['id'], str(i), '1', '', name, abilities, range_, kind, a, skill,
                                               strength, ap, damage])
        for i, text in enumerate(s.get('options', []), 1):
            t['Datasheets_options'][1].append([s['id'], str(i), '•', text])
        t['Datasheets_keywords'][1].append([s['id'], FACTION_KEYWORD[s['faction']], '', 'true'])
        for word in s.get('keywords', []):
            t['Datasheets_keywords'][1].append([s['id'], word, '', 'false'])
        for i, (ability, name, text, kind, parameter) in enumerate(s.get('abilities', []), 1):
            t['Datasheets_abilities'][1].append([s['id'], str(i), ability, '', name, text, kind, parameter])
    for faction, name, ident, cost, detachment, detachment_id, upgrade, text, sheets in ENHANCEMENTS:
        t['Enhancements'][1].append([faction, name, ident, cost, detachment, detachment_id, upgrade, '', text, ''])
        t['Datasheets_enhancements'][1].extend([sheet, ident] for sheet in sheets)
    return t


def write(folder, name, columns, rows):
    lines = ['|'.join(columns) + '|'] + ['|'.join(row) + '|' for row in rows]
    (folder / f'{name}.csv').write_text('﻿' + '\n'.join(lines) + '\n', encoding='utf-8', newline='\n')


def tables():
    return {**RULES, **datasheet_tables()}


if __name__ == '__main__':
    all_tables = tables()
    for folder, skip in ((OUT, ()), (UNITS_OUT, ('Stratagems',))):
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob('*.csv'):
            old.unlink()
        for name, (columns, rows) in all_tables.items():
            assert all(len(row) == len(columns) for row in rows), name
            if name not in skip:
                write(folder, name, columns, rows)
        print(f'Wrote {len(all_tables) - len(skip)} files to {folder}')
