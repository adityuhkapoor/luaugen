"""Byte-deterministic Luau literal emission.

Guarantees:
  * identical input data -> identical bytes (sorted keys, no locale/dict-order use)
  * every float round-trips exactly (shortest repr of the IEEE double)
  * keys that are Luau keywords or not identifiers are quoted
  * values Luau cannot represent faithfully (NaN, inf, ints beyond 2**53,
    nil holes inside arrays) are rejected instead of silently changed
"""

import hashlib
import math
import re
import struct

__all__ = ["literal", "module", "header", "f32", "sha256_bytes", "EmitError"]

GENERATOR = "luaugen"

# Luau reserved words plus contextual keywords that are unsafe as bare keys.
RESERVED = frozenset(
    "and break do else elseif end false for function if in local nil not or "
    "repeat return then true until while continue".split()
)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_SAFE_INT = 2 ** 53


class EmitError(ValueError):
    """Raised when a value cannot be represented exactly in Luau."""


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def f32(value):
    """Round a number to IEEE float32 and return it as a Python float.

    Use this in adapters when the source data is single precision: the emitted
    literal is then the exact double value of that float32, so Luau sees the
    bit-identical number (printing float32 with %.9g does not guarantee this).
    """
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _number(value, path):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE_INT:
            raise EmitError("%s: integer %d exceeds 2**53 and would lose precision in Luau" % (path, value))
        return str(value)
    if not math.isfinite(value):
        raise EmitError("%s: non-finite number %r" % (path, value))
    if value == 0:
        return "-0" if math.copysign(1.0, value) < 0 else "0"
    if value.is_integer() and abs(value) <= _MAX_SAFE_INT:
        return str(int(value))
    return repr(value)  # shortest string that round-trips the double


def _string(value):
    out = ['"']
    for char in value:
        code = ord(char)
        if char == '"':
            out.append('\\"')
        elif char == "\\":
            out.append("\\\\")
        elif char == "\n":
            out.append("\\n")
        elif char == "\r":
            out.append("\\r")
        elif char == "\t":
            out.append("\\t")
        elif code < 32 or code == 127:
            out.append("\\%03d" % code)
        elif code < 127:
            out.append(char)
        else:
            out.append("\\u{%X}" % code)
    out.append('"')
    return "".join(out)


def _key(key, path):
    if isinstance(key, bool) or key is None:
        raise EmitError("%s: unsupported table key %r" % (path, key))
    if isinstance(key, (int, float)):
        return "[" + _number(key, path) + "]"
    if isinstance(key, str):
        if _IDENT.match(key) and key not in RESERVED:
            return key
        return "[" + _string(key) + "]"
    raise EmitError("%s: unsupported table key type %s" % (path, type(key).__name__))


def _sort_key(key):
    # Numbers first (numerically), then strings (by code point). Deterministic
    # for mixed-key dicts, unlike sorting on str(key).
    if isinstance(key, (int, float)) and not isinstance(key, bool):
        return (0, float(key), "")
    return (1, 0.0, str(key))


def literal(value, indent=0, path="$"):
    """Return the Luau literal for a JSON-like Python value."""
    pad = "\t" * indent
    if value is None:
        return "nil"
    if isinstance(value, (bool, int, float)):
        return _number(value, path)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, (list, tuple)):
        if not value:
            return "{}"
        rows = ["{"]
        for i, item in enumerate(value):
            item_path = "%s[%d]" % (path, i + 1)
            if item is None:
                raise EmitError("%s: nil inside an array would create a hole; use a sentinel" % item_path)
            rows.append("%s\t%s," % (pad, literal(item, indent + 1, item_path)))
        rows.append(pad + "}")
        return "\n".join(rows)
    if isinstance(value, dict):
        if not value:
            return "{}"
        rows = ["{"]
        for key in sorted(value, key=_sort_key):
            item_path = "%s.%s" % (path, key)
            item = value[key]
            if item is None:
                continue  # assigning nil to a key is a no-op in Luau; omit it
            rows.append("%s\t%s = %s," % (pad, _key(key, item_path), literal(item, indent + 1, item_path)))
        rows.append(pad + "}")
        return "\n".join(rows)
    raise EmitError("%s: unsupported value type %s" % (path, type(value).__name__))


def header(sources, version, notes=()):
    """Provenance header. `sources` is a list of (label, sha256) pairs."""
    lines = [
        "--!nocheck",
        "-- Code generated by %s %s. DO NOT EDIT." % (GENERATOR, version),
    ]
    for label, digest in sources:
        lines.append("-- source: %s sha256:%s" % (label, digest))
    for note in notes:
        lines.append("-- " + note)
    return lines


def module(payload, sources, version, notes=()):
    """A complete ModuleScript source that returns `payload`."""
    lines = header(sources, version, notes)
    lines.append("return " + literal(payload))
    return "\n".join(lines) + "\n"
