"""Manifest-driven build and staleness check.

Manifest (JSON):
{
  "plugins": ["adapters.py"],            # optional, files defining adapters
  "targets": [
    {"adapter": "passthrough", "inputs": ["data/a.json"],
     "output": "generated/A.luau", "options": {}}
  ]
}
Paths are relative to the manifest's directory.
"""

import importlib.util
import json
import os

from . import __version__
from .adapters import REGISTRY, Input, Unsupported
from .emit import module, sha256_bytes


class BuildError(Exception):
    pass


def load_manifest(path):
    with open(path, "rb") as handle:
        manifest = json.loads(handle.read())
    root = os.path.dirname(os.path.abspath(path))
    for i, plugin in enumerate(manifest.get("plugins", [])):
        plugin_path = os.path.join(root, plugin)
        spec = importlib.util.spec_from_file_location("luaugen_plugin_%d" % i, plugin_path)
        if spec is None or spec.loader is None:
            raise BuildError("cannot load plugin %s" % plugin)
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    return manifest, root


def render_target(target, root):
    """Return (output_path, source_text) for one manifest target."""
    name = target["adapter"]
    if name not in REGISTRY:
        raise BuildError("unknown adapter %r (registered: %s)" % (name, ", ".join(sorted(REGISTRY))))
    inputs = []
    for rel in target["inputs"]:
        with open(os.path.join(root, rel), "rb") as handle:
            raw = handle.read()
        inputs.append(Input(rel, sha256_bytes(raw), json.loads(raw)))
    try:
        payload = REGISTRY[name](inputs, target.get("options", {}))
    except Unsupported as exc:
        raise BuildError("%s: UNSUPPORTED: %s" % (target["output"], exc))
    text = module(payload, [(i.path, i.sha256) for i in inputs], __version__,
                  notes=["adapter: " + name])
    return os.path.join(root, target["output"]), text


def build(manifest_path):
    manifest, root = load_manifest(manifest_path)
    written = []
    for target in manifest["targets"]:
        out, text = render_target(target, root)
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        written.append(out)
    return written


def check(manifest_path):
    """Return the list of outputs that are missing or differ from a fresh build."""
    manifest, root = load_manifest(manifest_path)
    stale = []
    for target in manifest["targets"]:
        out, text = render_target(target, root)
        try:
            with open(out, "r", encoding="utf-8", newline="") as handle:
                current = handle.read()
        except FileNotFoundError:
            current = None
        if current != text:
            stale.append(out)
    return stale
