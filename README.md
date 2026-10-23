# luaugen

Compile JSON data (configs, state tables, animation choice tables, anything
decoded from another tool) into **deterministic Luau ModuleScripts**, and
verify the result by running **reference cases** through your Luau code with
the `luau` CLI.

Built for porting data-driven systems to Roblox: instead of hand-transcribing
tables into Luau, you write a small adapter once, regenerate on every data
change, and let the acceptance harness tell you whether the port still
matches the reference behaviour.

Python 3.8+, no dependencies. `luau` CLI needed only for `accept`.

## What it guarantees

- **Byte-deterministic output**: sorted keys, fixed formatting; same input, same bytes.
- **Exact numbers**: floats are emitted as the shortest decimal that round-trips the IEEE double.
  For single-precision source data, pass values through `luaugen.emit.f32()` so Luau sees the bit-identical float32 value.
- **No silent damage**: NaN/inf, integers beyond 2^53, `nil` holes in arrays and unsupported key types raise errors.
  Luau keywords used as keys (`end`, `and`, ...) are quoted.
- **Provenance**: every file records the generator version, adapter and SHA-256 of each input.
- **No guessing**: adapters raise `Unsupported` when the data can't be converted without a judgement call; the build fails loudly.
- **Strict acceptance**: every expected field is compared, extra fields fail, runtime errors fail, and every case must report a result.
- **Staleness check**: `luaugen check` fails if any generated file differs from a fresh build.

## Quick start

```bash
pip install .
cd examples/blend1d
luaugen build                          # writes generated/BlendSpaces.luau
luaugen check                          # exit 1 if anything is stale
luaugen accept cases.json --manifest luaugen.json
# cases.json: 7 cases: 7 passed, 0 failed, 0 errors, 0 missing
```

## Manifest

```json
{
  "plugins": ["adapters.py"],
  "targets": [
    {"adapter": "blend1d", "inputs": ["data/locomotion.json"], "output": "generated/BlendSpaces.luau"}
  ]
}
```

Built-in adapters: `passthrough` (optionally `"options": {"select": "a.b"}`) and
`keyed` (index records by `"key"`, rejecting duplicates).

## Writing an adapter

```python
from luaugen.adapters import Unsupported, adapter, single

@adapter("blend1d")
def blend1d(inputs, options):
    data = single(inputs, "blend1d").data      # parsed JSON; .path and .sha256 also available
    ...                                         # return plain dicts/lists/numbers/strings
    raise Unsupported("explain what is ambiguous")
```

Adapters must be pure functions of their inputs and options.

## Acceptance fixtures

```json
{
  "data": "generated/BlendSpaces.luau",
  "evaluator": "Blend1D.luau",
  "entry": "evaluate",
  "tolerance": 1e-12,
  "cases": [
    {"name": "idle-walk midpoint", "args": ["locomotion", 1], "expect": {"a": "idle", "b": "walk", "weight": 0.5}},
    {"name": "unknown space errors", "args": ["swim", 1], "expectError": true}
  ]
}
```

The evaluator is a ModuleScript returning a table; `entry(data, ...args)` is
called for each case inside `pcall`. Record `expect` values from the system
you are porting, never from the port itself, or the test only checks the
port against itself.

## Limits

- Inputs are JSON. Decode binary formats with your own tools first.
- `accept` runs plain Luau, so evaluators can't use Roblox engine APIs (`Instance`, `workspace`, ...).
  Keep the logic you want to verify pure.
- Very large tables can hit Luau compiler limits on constants; split them across targets.

## License

MIT
