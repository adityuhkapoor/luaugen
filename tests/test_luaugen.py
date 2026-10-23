import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest

from luaugen import emit
from luaugen.accept import parse, run
from luaugen.adapters import REGISTRY, Input, Unsupported
from luaugen.build import build, check

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(HERE, "..", "examples", "blend1d")
LUAU = shutil.which("luau")


def luau_eval(source):
    with tempfile.NamedTemporaryFile("w", suffix=".luau", delete=False) as handle:
        handle.write(source)
        path = handle.name
    try:
        return subprocess.run([LUAU, path], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, check=True).stdout
    finally:
        os.unlink(path)


class EmitTests(unittest.TestCase):
    def test_deterministic_and_sorted(self):
        a = emit.literal({"b": 1, "a": [1, 2], 3: "x", 1: "y"})
        b = emit.literal({1: "y", 3: "x", "a": [1, 2], "b": 1})
        self.assertEqual(a, b)
        self.assertLess(a.index("[1]"), a.index("[3]"))
        self.assertLess(a.index("[3]"), a.index("a ="))

    def test_reserved_and_non_identifier_keys_are_quoted(self):
        out = emit.literal({"end": 1, "two words": 2, "ok_key": 3, "continue": 4})
        self.assertIn('["end"] = 1', out)
        self.assertIn('["two words"] = 2', out)
        self.assertIn('["continue"] = 4', out)
        self.assertIn("ok_key = 3", out)

    def test_rejects_unrepresentable_values(self):
        for bad in (float("nan"), float("inf"), 2 ** 60, [1, None, 3]):
            with self.assertRaises(emit.EmitError):
                emit.literal(bad)

    def test_none_in_dict_is_omitted(self):
        self.assertNotIn("a =", emit.literal({"a": None, "b": 1}))

    def test_f32_is_exact(self):
        value = emit.f32(0.2)
        self.assertEqual(struct.pack("<f", value), struct.pack("<f", 0.2))
        self.assertEqual(float(emit.literal(value)), value)

    def test_strings_escape(self):
        self.assertEqual(emit.literal('a"b\\c\n\x01é'), '"a\\"b\\\\c\\n\\001\\u{E9}"')


@unittest.skipUnless(LUAU, "luau CLI not installed")
class LuauRoundTripTests(unittest.TestCase):
    def test_floats_round_trip_bit_exact(self):
        values = [0.1, 1 / 3, emit.f32(0.2), emit.f32(-1.7), 1e-300, 123456.789, -0.0, 2.0 ** 52 + 0.5, 5e-324]
        table = emit.literal(values)
        out = luau_eval("local t = " + table + "\nfor _, v in t do print(string.format('%.17g', v), 1/v < 0) end")
        lines = out.splitlines()
        self.assertEqual(len(lines), len(values))
        for value, line in zip(values, lines):
            text, negative = line.split()
            self.assertEqual(float(text), value, line)
            if value == 0:
                self.assertEqual(negative == "true", str(value).startswith("-"))

    def test_strings_round_trip(self):
        value = 'quote" back\\ tab\t nl\n ctl\x07 é 漢'
        out = luau_eval("print(" + emit.literal(value) + ")")
        self.assertEqual(out[:-1], value)

    def test_reserved_keys_parse(self):
        out = luau_eval("local t = " + emit.literal({"end": 1, "and": 2}) + "\nprint(t[\"end\"] + t[\"and\"])")
        self.assertEqual(out.strip(), "3")


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        shutil.copytree(EXAMPLE, os.path.join(self.tmp, "ex"))
        self.manifest = os.path.join(self.tmp, "ex", "luaugen.json")
        REGISTRY.pop("blend1d", None)

    def tearDown(self):
        shutil.rmtree(self.tmp)
        REGISTRY.pop("blend1d", None)

    def test_build_twice_identical_and_check_detects_stale(self):
        out = build(self.manifest)[0]
        first = open(out, "rb").read()
        REGISTRY.pop("blend1d", None)
        build(self.manifest)
        self.assertEqual(first, open(out, "rb").read())
        REGISTRY.pop("blend1d", None)
        self.assertEqual(check(self.manifest), [])
        data_path = os.path.join(self.tmp, "ex", "data", "locomotion.json")
        doc = json.load(open(data_path))
        doc["blendSpaces"][0]["samples"][0]["at"] = 7
        json.dump(doc, open(data_path, "w"))
        REGISTRY.pop("blend1d", None)
        self.assertEqual(check(self.manifest), [out])

    def test_unsupported_is_reported_not_guessed(self):
        data_path = os.path.join(self.tmp, "ex", "data", "locomotion.json")
        doc = json.load(open(data_path))
        doc["blendSpaces"][0]["samples"].append({"at": 2, "clip": "jog"})
        json.dump(doc, open(data_path, "w"))
        with self.assertRaisesRegex(Exception, "UNSUPPORTED"):
            build(self.manifest)

    def test_keyed_rejects_duplicates(self):
        with self.assertRaises(Unsupported):
            REGISTRY["keyed"]([Input("x", "0", [{"id": 1}, {"id": 1}])], {"key": "id"})


class ParseTests(unittest.TestCase):
    fixture = {"cases": [{"name": "a"}, {"name": "b"}]}

    def test_missing_results_fail(self):
        result = parse("@@luaugen\tPASS\t1\n", self.fixture)
        self.assertFalse(result.ok)
        self.assertIn("b", result.missing)

    def test_unfinished_runner_fails(self):
        result = parse("@@luaugen\tPASS\t1\n@@luaugen\tPASS\t2\n", self.fixture)
        self.assertFalse(result.ok)

    def test_evaluator_output_cannot_spoof_results(self):
        result = parse("PASS\t1\nPASS\t2\n@@luaugen\tDONE\t2\n", self.fixture)
        self.assertFalse(result.ok)
        self.assertEqual(len(result.missing), 2)


@unittest.skipUnless(LUAU, "luau CLI not installed")
class AcceptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        shutil.copytree(EXAMPLE, os.path.join(self.tmp, "ex"))
        REGISTRY.pop("blend1d", None)
        build(os.path.join(self.tmp, "ex", "luaugen.json"))
        self.cases_path = os.path.join(self.tmp, "ex", "cases.json")

    def tearDown(self):
        shutil.rmtree(self.tmp)
        REGISTRY.pop("blend1d", None)

    def edit(self, fn):
        doc = json.load(open(self.cases_path))
        fn(doc)
        json.dump(doc, open(self.cases_path, "w"))

    def test_example_passes(self):
        result = run(self.cases_path)
        self.assertTrue(result.ok, result.summary())
        self.assertEqual(len(result.passed), 7)

    def test_wrong_value_fails(self):
        self.edit(lambda d: d["cases"][1]["expect"].update(weight=0.4))
        result = run(self.cases_path)
        self.assertEqual([name for name, _ in result.failed], ["idle-walk midpoint"])

    def test_extra_and_missing_fields_fail(self):
        def mutate(doc):
            del doc["cases"][1]["expect"]["b"]
            doc["cases"][2]["expect"]["extra"] = 1
        self.edit(mutate)
        result = run(self.cases_path)
        self.assertEqual(len(result.failed), 2)

    def test_runtime_error_is_not_a_pass(self):
        def mutate(doc):
            doc["cases"][5].pop("expectError")
            doc["cases"][5]["expect"] = {"a": "idle", "weight": 0}
        self.edit(mutate)
        result = run(self.cases_path)
        self.assertEqual([name for name, _ in result.errors], ["unknown space errors"])
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
