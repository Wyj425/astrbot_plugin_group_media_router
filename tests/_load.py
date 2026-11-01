import importlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType('router_test')
package.__path__ = [str(ROOT)]
sys.modules.setdefault(package.__name__, package)


def load(name):
    return importlib.import_module('router_test.' + name)
