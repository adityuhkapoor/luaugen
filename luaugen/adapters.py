"""Adapter registry.

An adapter turns decoded input documents into plain JSON-like data that the
emitter writes as a Luau table. Adapters must be pure: same inputs and
options -> same payload. When data cannot be converted without guessing,
raise Unsupported instead of picking a default.
"""

from collections import namedtuple

Input = namedtuple("Input", "path sha256 data")
REGISTRY = {}


class Unsupported(Exception):
    """The input is valid but cannot be compiled without guessing."""


def adapter(name):
    def register(fn):
        if name in REGISTRY:
            raise ValueError("adapter %r already registered" % name)
        REGISTRY[name] = fn
        return fn
    return register


def dig(data, path):
    """Follow a dotted path ("a.b.0.c"); list indices are 0-based."""
    node = data
    for part in path.split(".") if path else []:
        if isinstance(node, list):
            node = node[int(part)]
        else:
            node = node[part]
    return node


def single(inputs, adapter_name):
    if len(inputs) != 1:
        raise Unsupported("%s takes exactly one input, got %d" % (adapter_name, len(inputs)))
    return inputs[0]


@adapter("passthrough")
def passthrough(inputs, options):
    """Emit one input unchanged, or the sub-tree at options["select"]."""
    return dig(single(inputs, "passthrough").data, options.get("select", ""))


@adapter("keyed")
def keyed(inputs, options):
    """Index an array of records by options["key"]; duplicate keys are an error."""
    records = dig(single(inputs, "keyed").data, options.get("select", ""))
    key = options["key"]
    out = {}
    for i, record in enumerate(records):
        if key not in record:
            raise Unsupported("record %d has no %r field" % (i, key))
        value = record[key]
        if value in out:
            raise Unsupported("duplicate key %r (records would be silently dropped)" % (value,))
        out[value] = {k: v for k, v in record.items() if k != key} if options.get("drop_key") else record
    return out
