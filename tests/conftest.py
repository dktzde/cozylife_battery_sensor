"""Load the integration's Home Assistant-free modules without Home Assistant.

The package ``__init__`` imports Home Assistant, so the tests register an empty
package object and import the plain modules (``wake_schedule``, ``probe``,
``cozylife_api`` ...) from it directly.
"""

from __future__ import annotations

from pathlib import Path
import sys
import types

COMPONENT_DIR = Path(__file__).parents[1] / "custom_components" / "cozylife_local"

_package = types.ModuleType("cozylife_local")
_package.__path__ = [str(COMPONENT_DIR)]
sys.modules.setdefault("cozylife_local", _package)
