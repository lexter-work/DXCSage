import importlib
import pkgutil

import sage.workflows as pkg
from sage.workflows.base import Workflow


def discover() -> dict[str, type[Workflow]]:
    found = {}
    for m in pkgutil.iter_modules(pkg.__path__):
        if m.name in ("base", "registry"):
            continue
        mod = importlib.import_module(f"sage.workflows.{m.name}")
        for obj in vars(mod).values():
            if isinstance(obj, type) and issubclass(obj, Workflow) and obj is not Workflow and getattr(obj, "name", None):
                found[obj.name] = obj
    return found
