from __future__ import annotations

import importlib
import importlib.metadata
import inspect
import json
import os
import sys


def valid_path(dotted):
    return bool(dotted) and all(part.isidentifier() for part in dotted.split("."))


def resolve(module, name):
    if not valid_path(module):
        raise ValueError("invalid module path: " + repr(module))
    imported = importlib.import_module(module)
    if not name:
        return imported
    target = imported
    for part in name.split("."):
        if not part.isidentifier():
            raise ValueError("invalid attribute name: " + repr(name))
        try:
            target = getattr(target, part)
        except AttributeError:
            if not inspect.ismodule(target):
                raise
            target = importlib.import_module(target.__name__ + "." + part)
    return target


def signature_of(obj):
    if not callable(obj) or inspect.ismodule(obj):
        return None
    try:
        return str(inspect.signature(obj))
    except (ValueError, TypeError):
        return None


def describe(exc):
    return type(exc).__name__ + ": " + str(exc)


def install_info(package):
    info = {"version": None, "file": None, "direct_url": False, "error": None}
    try:
        dist = importlib.metadata.distribution(package)
        info["version"] = dist.version
        info["direct_url"] = dist.read_text("direct_url.json") is not None
    except BaseException as exc:
        info["error"] = describe(exc)
    try:
        info["file"] = getattr(importlib.import_module(package), "__file__", None)
    except BaseException as exc:
        info["error"] = (info["error"] or "") + " " + describe(exc)
    return info


def probe(entry):
    record = {"import_error": None, "alias_errors": [], "signature": None}
    try:
        target = resolve(entry["module"], entry.get("name"))
    except BaseException as exc:
        record["import_error"] = describe(exc)
        return record
    for alias in entry.get("aliases", []):
        alias_module, _, alias_name = alias.rpartition(".")
        try:
            other = resolve(alias_module, alias_name)
        except BaseException as exc:
            record["alias_errors"].append(alias + " -> " + describe(exc))
            continue
        if other is not target:
            record["alias_errors"].append(alias + " -> not identical")
    record["signature"] = signature_of(target)
    return record


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.getcwd()) != here]
    entry = json.loads(sys.argv[1])
    install = install_info(entry["package"])
    report = {
        "python": "{}.{}".format(*sys.version_info[:2]),
        "install": install,
        "result": probe(entry),
    }
    sys.stdout.write("\n" + json.dumps(report) + "\n")


main()
