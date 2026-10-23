"""Differential acceptance: run recorded reference cases through generated
data + your Luau evaluator with the `luau` CLI, and compare every field.

Fixture file (JSON):
{
  "data": "generated/Blend.luau",       # generated module (relative to fixture)
  "evaluator": "eval.luau",             # ModuleScript returning a table of functions
  "entry": "evaluate",                  # function called as entry(data, ...args)
  "tolerance": 0,                       # absolute numeric tolerance (default exact)
  "cases": [
    {"name": "mid", "args": [0.5], "expect": {"a": 1, "b": 2, "weight": 0.5}},
    {"name": "bad", "args": [null], "expectError": true}
  ]
}

Comparison is strict: missing AND extra fields fail, a runtime error fails
unless the case says expectError, and the run fails unless exactly one result
is reported for every case. Expected values are the reference ground truth;
record them from the system you are porting, never from the port itself.
"""

import json
import os
import subprocess
import tempfile

from .emit import literal

MARK = "@@luaugen"

_RUNNER = r"""
local data = (function()
%(data)s
end)()
local Evaluator = (function()
%(evaluator)s
end)()
local cases = %(cases)s
local tolerance = %(tolerance)s
local MARK = "%(mark)s"

local function show(v)
	if type(v) == "string" then return string.format("%%q", v) end
	if type(v) == "number" then return string.format("%%.17g", v) end
	return tostring(v)
end

local function equal(expected, actual, path)
	if type(expected) ~= type(actual) then
		return false, path .. ": expected " .. type(expected) .. " " .. show(expected) .. ", got " .. type(actual) .. " " .. show(actual)
	end
	if type(expected) == "number" then
		if expected ~= expected or actual ~= actual then
			return false, path .. ": NaN"
		end
		if math.abs(expected - actual) > tolerance or (tolerance == 0 and expected ~= actual) then
			return false, path .. ": expected " .. show(expected) .. ", got " .. show(actual)
		end
		return true
	end
	if type(expected) ~= "table" then
		if expected ~= actual then
			return false, path .. ": expected " .. show(expected) .. ", got " .. show(actual)
		end
		return true
	end
	for k, v in expected do
		local ok, msg = equal(v, actual[k], path .. "." .. tostring(k))
		if not ok then return false, msg end
	end
	for k in actual do
		if expected[k] == nil then
			return false, path .. "." .. tostring(k) .. ": unexpected field " .. show(actual[k])
		end
	end
	return true
end

local function report(status, i, msg)
	print(MARK .. "\t" .. status .. "\t" .. i .. (msg and ("\t" .. string.gsub(tostring(msg), "[\r\n\t]", " ")) or ""))
end

local entry = Evaluator[%(entry)s]
assert(type(entry) == "function", "evaluator has no function named " .. %(entry)s)
for i, case in ipairs(cases) do
	local ok, result = pcall(entry, data, table.unpack(case.args, 1, case.args.n))
	if case.expectError then
		if ok then report("FAIL", i, "expected an error, got a result") else report("PASS", i) end
	elseif not ok then
		report("ERROR", i, result)
	else
		local same, msg = equal(case.expect, result, "result")
		if same then report("PASS", i) else report("FAIL", i, msg) end
	end
end
print(MARK .. "\tDONE\t" .. #cases)
"""


class Result(object):
    def __init__(self, total):
        self.total = total
        self.passed, self.failed, self.errors, self.missing = [], [], [], []

    @property
    def ok(self):
        return (self.total > 0 and len(self.passed) == self.total
                and not self.failed and not self.errors and not self.missing)

    def summary(self):
        return "%d cases: %d passed, %d failed, %d errors, %d missing" % (
            self.total, len(self.passed), len(self.failed), len(self.errors), len(self.missing))


def _args(values):
    # Arrays cannot hold nil, so pass args as {n = count, [i] = value}.
    out = {"n": len(values)}
    for i, value in enumerate(values):
        if value is not None:
            out[i + 1] = value
    return out


def build_runner(fixture, root):
    with open(os.path.join(root, fixture["data"]), "r", encoding="utf-8") as handle:
        data = handle.read()
    with open(os.path.join(root, fixture["evaluator"]), "r", encoding="utf-8") as handle:
        evaluator = handle.read()
    cases = []
    for case in fixture["cases"]:
        entry = {"args": _args(case.get("args", []))}
        if case.get("expectError"):
            entry["expectError"] = True
        else:
            if "expect" not in case or case["expect"] is None:
                raise ValueError("case %r has no expect (use expectError for error cases)" % case.get("name"))
            entry["expect"] = case["expect"]
        cases.append(entry)
    return _RUNNER % {
        "data": data,
        "evaluator": evaluator,
        "cases": literal(cases),
        "tolerance": literal(float(fixture.get("tolerance", 0))),
        "entry": literal(fixture.get("entry", "evaluate")),
        "mark": MARK,
    }


def parse(output, fixture):
    """Turn runner stdout into a Result; anything unaccounted for fails."""
    names = [case.get("name", str(i + 1)) for i, case in enumerate(fixture["cases"])]
    result = Result(len(names))
    seen = {}
    done = None
    for line in output.splitlines():
        if not line.startswith(MARK + "\t"):
            continue
        parts = line.split("\t", 3)
        if parts[1] == "DONE":
            done = int(parts[2])
            continue
        index = int(parts[2]) - 1
        if index in seen or not 0 <= index < len(names):
            raise RuntimeError("runner reported case %d twice or out of range" % (index + 1))
        seen[index] = (parts[1], parts[3] if len(parts) > 3 else "")
    for index, name in enumerate(names):
        status, msg = seen.get(index, ("MISSING", ""))
        if status == "PASS":
            result.passed.append(name)
        elif status == "FAIL":
            result.failed.append((name, msg))
        elif status == "ERROR":
            result.errors.append((name, msg))
        else:
            result.missing.append(name)
    if done != len(names):
        result.missing.append("<runner did not finish: DONE %s of %d>" % (done, len(names)))
    return result


def run(fixture_path, luau="luau", timeout=300):
    with open(fixture_path, "rb") as handle:
        fixture = json.loads(handle.read())
    root = os.path.dirname(os.path.abspath(fixture_path))
    source = build_runner(fixture, root)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "runner.luau")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        proc = subprocess.run([luau, path], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=timeout)
    result = parse(proc.stdout, fixture)
    if proc.returncode != 0:
        result.missing.append("<luau exited %d: %s>" % (proc.returncode, proc.stderr.strip()[-500:]))
    return result
