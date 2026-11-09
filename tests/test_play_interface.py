"""
The game engine's interface (play/game.py `__all__`): the rest of the app uses only what it lists. play/game.py,
play/mission_state.py and play/tactical.py are the engine and may use its private helpers; tests may too.
"""

import ast
from pathlib import Path

from combat_sim.play import game

SRC = Path(__file__).resolve().parent.parent / 'src' / 'combat_sim'
ENGINE = {'game.py', 'mission_state.py', 'tactical.py'}


def engine_names_used(path):
    """Names a module takes from the engine: `from .game import ...`, or `<alias>.<name>` after importing it whole."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names, aliases = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ''
            if module == 'game' or module.endswith('play.game'):
                names |= {a.name for a in node.names}
            elif module in ('', 'play') or module.endswith('.play'):
                aliases |= {a.asname or a.name for a in node.names if a.name == 'game'}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
            names.add(node.attr)
    return names


def test_the_rest_of_the_app_uses_only_the_engines_interface():
    outside = {}
    for path in SRC.rglob('*.py'):
        if path.parent.name == 'play' and path.name in ENGINE:
            continue
        stray = engine_names_used(path) - set(game.__all__)
        if stray:
            outside[str(path.relative_to(SRC))] = sorted(stray)
    assert not outside, f'Add these to play/game.py __all__ (or keep them inside the engine): {outside}'


def test_everything_the_interface_lists_exists():
    assert [name for name in game.__all__ if not hasattr(game, name)] == []
    assert len(set(game.__all__)) == len(game.__all__)
