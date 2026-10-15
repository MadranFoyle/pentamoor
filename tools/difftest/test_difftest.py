"""Tests for the difftest pipeline. Run with: python3 -m pytest tools/difftest"""

import copy
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import make_doc_vectors  # noqa: E402
import run_vectors as rv  # noqa: E402

VECTORS = os.path.join(HERE, "vectors")


@pytest.fixture(scope="module")
def harness():
    return rv.build_harness()


def load(name):
    with open(os.path.join(VECTORS, name), encoding="utf-8") as f:
        return json.load(f)


def run(tmp_path, harness, vector, name="v.json"):
    path = tmp_path / name
    path.write_text(json.dumps(vector))
    return rv.run_vector(str(path), harness)


# --------------------------------------------------------------------------------------------------
# The seed vectors


def test_every_vector_passes_or_is_unimplemented(harness):
    for path in sorted(os.listdir(VECTORS)):
        status, messages, _ = rv.run_vector(os.path.join(VECTORS, path), harness)
        expected = "UNIMPLEMENTED" if "unimplemented" in path else "PASS"
        assert status == expected, (path, messages)


def test_runner_exit_codes(harness):
    assert rv.main(["--harness", harness]) == 0
    assert rv.main(["--harness", harness, "--strict"]) == 1


def test_doc_vectors_are_up_to_date(tmp_path):
    make_doc_vectors.main(str(tmp_path))
    try:
        generated = sorted(os.listdir(tmp_path))
        committed = sorted(f for f in os.listdir(VECTORS) if f.startswith("doc_"))
        assert generated == committed
        match, mismatch, errors = filecmp.cmpfiles(str(tmp_path), VECTORS, generated, shallow=False)
        assert not mismatch and not errors, "run tools/difftest/make_doc_vectors.py"
    finally:
        make_doc_vectors.OUT = make_doc_vectors.os.path.join(make_doc_vectors.HERE, "vectors")


def test_doc_numbers_are_in_the_vectors():
    # Llanowar Elves 1/1, Durkwood Boars 4, Killer Bees ability 0x20, Forest index 2 and a mana source.
    assert load("doc_query_power_elves_recompute.json")["expected_return"] == 1
    assert load("doc_query_toughness_elves_recompute.json")["expected_return"] == 1
    assert load("doc_query_power_boars_recompute.json")["expected_return"] == 4
    assert load("doc_query_abilities_bees_recompute.json")["expected_return"] == 0x20
    assert load("doc_query_index_forest.json")["expected_return"] == 2
    assert load("doc_is_mana_source_forest_duel.json")["expected_return"] == 1
    assert load("doc_color_type_flags_forest.json")["expected_return"] == 0
    assert load("doc_color_type_flags_green_creature_elves.json")["expected_return"] == 0x2000


# --------------------------------------------------------------------------------------------------
# The runner notices what is wrong


def test_wrong_return_fails(tmp_path, harness):
    v = load("doc_query_power_elves_recompute.json")
    v["expected_return"] = 2
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "FAIL" and "return 0x1, expected 0x2" in messages[0]


def test_bool_return_compares_the_low_byte_only(tmp_path, harness):
    v = load("doc_is_mana_source_forest_duel.json")
    v["expected_return"] = "0x7c3a0001"   # garbage above AL, as a trace of a bool function can show
    assert run(tmp_path, harness, v)[0] == "PASS"


def test_missing_input_memory_is_reported(tmp_path, harness):
    v = load("doc_is_mana_source_forest_duel.json")
    v["memory_in"] = v["memory_in"][:1]  # drop the master record
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "FAIL" and any("undefined byte" in m for m in messages)


def test_wrong_memory_out_fails(tmp_path, harness):
    v = load("doc_clear_duel.json")
    v["memory_out_expected"][0]["dwords"][0] = "0x00000001"
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "FAIL" and any("memory at" in m for m in messages)


def test_unlisted_write_fails_when_exhaustive(tmp_path, harness):
    v = load("doc_clear_duel.json")
    v["memory_out_expected"] = v["memory_out_expected"][:1]
    v["memory_out_expected"][0]["dwords"] = v["memory_out_expected"][0]["dwords"][:1]
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "FAIL" and any("changed but not in memory_out_expected" in m for m in messages)
    v["memory_out_exhaustive"] = False
    assert run(tmp_path, harness, v)[0] == "PASS"


def test_call_mismatches(tmp_path, harness):
    # The stand-in push calls the free-slot finder once; the colour/type-flags vectors no longer have
    # calls (their helpers are native), so this vector is the one that exercises the call replay.
    base = load("doc_push_stand_in_object.json")
    assert len(base["calls"]) == 1
    v = copy.deepcopy(base)
    v["calls"][0]["args"][1] = 0x1C1
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "FAIL" and "args" in messages[0]
    v = copy.deepcopy(base)
    v["calls"] = []
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "FAIL" and "unexpected call" in messages[0]
    v = copy.deepcopy(base)
    v["calls"].append(dict(v["calls"][0]))
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "FAIL" and "not made" in messages[-1]
    v = copy.deepcopy(base)
    v["calls"][0]["callee"] = "0x00401000"
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "FAIL" and "expects 0x00401000" in messages[0]


def test_callee_side_effects_are_replayed(tmp_path, harness):
    # The finder's own writes (here: the player's card count) land before the push goes on.
    v = load("doc_push_stand_in_object.json")
    count_addr = "0x00666408"
    v["calls"][0]["memory_writes"] = [{"addr": count_addr, "dwords": [8]}]
    v["memory_out_expected"].append({"addr": count_addr, "dwords": [8]})
    assert run(tmp_path, harness, v)[0] == "PASS"


def test_bad_vectors_are_errors(tmp_path, harness):
    v = load("doc_clear_duel.json")
    del v["args"]
    assert run(tmp_path, harness, v)[0] == "ERROR"
    v = load("doc_clear_duel.json")
    v["address"] = "0x00401000"
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "ERROR" and "entry address mismatch" in messages[0]
    v = load("doc_clear_duel.json")
    v["function"] = "Magic_NotNativeYet"
    assert run(tmp_path, harness, v)[0] == "ERROR"
    v = load("doc_clear_duel.json")
    v["memory_in"] = [{"addr": "0x1000", "bytes": [300]}]
    assert run(tmp_path, harness, v)[0] == "ERROR"


# --------------------------------------------------------------------------------------------------
# The C side


def test_native_code_compiles_without_warnings(tmp_path):
    cc = os.environ.get("CC") or "cc"
    if not shutil.which(cc):
        pytest.skip("no C compiler")
    out = tmp_path / "h"
    proc = subprocess.run([cc, "-std=c99", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-o", str(out)]
                          + rv.SOURCES, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def layout_addresses():
    with open(os.path.join(rv.NATIVE, "layout.c"), encoding="utf-8") as f:
        text = f.read()
    out = {}
    for program in ("MAGIC", "DUEL"):
        block = text.split(f"const Layout LAYOUT_{program} = {{", 1)[1].split("\n};", 1)[0]
        out[program] = {m.group(1): int(m.group(2), 16)
                        for m in re.finditer(r"\[((?:FN|CALLEE)_[A-Z_0-9]+)\] = 0x([0-9a-fA-F]+)", block)}
    return out


def _game_programs():
    game = os.environ.get("PENTAMOOR_GAME") or os.path.join(rv.REPO, "sources", "installed", "Magic", "Program")
    return game if all(os.path.exists(os.path.join(game, e)) for e in ("MAGIC.EXE", "DUEL.EXE")) else None


@pytest.mark.skipif(_game_programs() is None, reason="needs the installed game")
def test_layout_code_addresses_are_function_starts():
    """Every entry and callee address in layout.c starts a function in that program (as tools/lift/fnscan.py finds them in its executable)."""
    sys.path.insert(0, os.path.join(rv.REPO, "tools", "lift"))
    import fnscan  # noqa: PLC0415
    for program, addrs in layout_addresses().items():
        starts = set(fnscan.scan_file(os.path.join(_game_programs(), program + ".EXE")))
        # every FN_* entry and every remaining CALLEE_* of engine.h, in each program
        import record_vectors as rec  # noqa: PLC0415
        assert len(addrs) == len(rec.NATIVE_FUNCTIONS) + len(rec.CALLEES_INFO) - len(rec.DYNAMIC_CALLEES), len(addrs)
        missing = {k: hex(a) for k, a in addrs.items() if a and a not in starts}   # 0: the program has no such function
        assert not missing, (program, missing)


def test_record_vectors_tables_match_native_code():
    """record_vectors.py's NATIVE_FUNCTIONS/CALLEES_INFO must name exactly the FN_*/CALLEE_* members
    src/native/engine.h declares, in both programs' layout.c, so the recorder's hardcoded tables cannot
    quietly drift from what the native code actually calls when a function is added or removed. This
    needs neither unicorn nor the game."""
    import record_vectors as rec  # noqa: PLC0415 (imported here: needs no unicorn to run this test)

    fn_names = {n for n, _, _ in rec.NATIVE_FUNCTIONS}
    callee_names = {n for n, _, _ in rec.CALLEES_INFO} | {"CALLEE_FUNCTION"}   # the generic callee of lifted code (lift_bridge.c) has no table row
    for program in ("MAGIC", "DUEL"):
        entries, callees, fn_order, callee_order = rec.load_layout(program)
        assert set(fn_order) == fn_names, (program, "FN_* mismatch", set(fn_order) ^ fn_names)
        assert set(callee_order) == callee_names, (program, "CALLEE_* mismatch", set(callee_order) ^ callee_names)
        assert set(entries) == set(fn_order), (program, "layout.c .entry vs engine.h NativeFn")
        assert set(callees) == set(callee_order) - rec.DYNAMIC_CALLEES - {"CALLEE_FUNCTION"}, (program, "layout.c .callee vs engine.h Callee")


def test_memcpy_instruction_counts_are_what_the_original_spends(tmp_path):
    """crt_memcpy_instructions (src/native/crt.c) against counts measured by running the original's memcpy, 0x004d99b0 of
    DUEL.EXE, in the emulator: instructions plus one per `rep` iteration plus one for the iteration that ends it (what the
    emulator counts). The measuring needs the game; these values are what it gave."""
    cc = os.environ.get("CC") or "cc"
    if not shutil.which(cc):
        pytest.skip("no C compiler")
    base = 0x110000
    # (dst, src, n, instructions)
    cases = [(base + 0x1000, base + 0x8000, 0, 21), (base + 0x1000, base + 0x8000, 1, 23), (base + 0x1000, base + 0x8000, 4, 22),
             (base + 0x1001, base + 0x8000, 0, 19), (base + 0x1001, base + 0x8000, 12, 31), (base + 0x1001, base + 0x8000, 13, 37),
             (base + 0x1003, base + 0x8000, 13, 34), (base + 0x1002, base + 0x8000, 17, 39), (base + 0x1000, base + 0x8000, 4000, 1021),
             (base + 0x1001, base + 0x8000, 4000, 1034), (base + 0x1000, base + 0x8000, 0xb640, 11685),
             (base + 0x4001, base + 0x4000, 12, 41), (base + 0x4004, base + 0x4000, 12, 34), (base + 0x4000, base + 0x4001, 12, 24)]
    main = tmp_path / "main.c"
    main.write_text('#include <stdio.h>\n#include <stdint.h>\nuint64_t crt_memcpy_instructions(uint32_t, uint32_t, uint32_t);\n'
                    "int main(void) {\n" + "".join(f'    printf("%llu\\n", (unsigned long long)crt_memcpy_instructions({d}u, {s}u, {n}u));\n' for d, s, n, _ in cases)
                    + "    return 0;\n}\n")
    exe = tmp_path / "t"
    proc = subprocess.run([cc, "-std=c99", "-O1", "-I", rv.NATIVE, "-o", str(exe), str(main)] + [p for p in rv.SOURCES if not p.endswith("harness.c")],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    got = [int(x) for x in subprocess.run([str(exe)], capture_output=True, text=True).stdout.split()]
    assert got == [c[3] for c in cases]
