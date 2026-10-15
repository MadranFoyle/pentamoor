#!/usr/bin/env python3
"""Write the hand-made vectors in tools/difftest/vectors/doc_*.json.

They prove the pipeline with numbers from docs/SYMBOL_VERIFICATION.md (the DUEL.EXE emulator runs):
card-table indexes (Llanowar Elves 56, Durkwood Boars 61, Killer Bees 323, Forest 2), printed power
and toughness, the ability and mana-source bits, what each query code returns, and the pushes seen
while playing a Forest and casting Llanowar Elves. Every expected value below was worked out by hand
from the decompiled body, never by running the native code. Where the doc gives no number (a card id,
an unrelated global's value) the vector says the value is illustrative.

Vectors traced from the original (SPEC.md) will replace these; this script is only for the seed set.

    python3 tools/difftest/make_doc_vectors.py
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "vectors")
DOC = "docs/SYMBOL_VERIFICATION.md"

# Addresses from src/native/layout.c.
LAYOUT = {
    "DUEL": dict(slot=0x006826C0, master=0x004FF590, count=0x006764B8, entries=0x0068F240,
                 objects=0x0068EFB0, aux=0x0068F120, step=0x00666960, flags=0x00666460,
                 stack_card=0x0068EEE0, cur_step=0x0068F230, step_fallback=0x0068F2C4,
                 ai=0x0066AAF4, depth=0x0068EED8, counter=0x006663E0, saved=0x005EF980,
                 src_player=0x0068ECB0, src_slot=0x00690C48, card_id=0x00681ECC,
                 card_color=0x0068EE64, target_slot=0x0068ECFC, result=0x0066642C,
                 mode=0x00681EB0, token_base=0x0068F104,
                 f_query=0x0048B81A, f_mana=0x0048CA2A, f_drop=0x0048E251, f_push=0x0048D878,
                 f_clear=0x0048D3BF, f_color=0x004521E2,
                 c_find_free=0x004D695B, f_remap_f9=0x004AF7BB, f_remap_ff=0x004AF74C,
                 ai_cursor=0x0050B37C, ai_best_choice=0x00511600, ai_peeked=0x00666410,
                 f_peek_choice=0x00430768, f_cursor_back=0x004308E4,
                 f_scan=0x0048C5A8, c_scan_check=0x0048AF80, c_broadcast=0x0048C50B, c_combat=0x0048B64F,
                 scan_event=0x0068DD04, scan_counter=0x00666728, scan_depth=0x0068EF48, scan_order_p=0x00690320,
                 scan_order_s=0x00681EE0, scan_current=0x00666448, master_count=0x00665ED0, turn_player=0x00666458,
                 scan_flag=0x0068F0F4, global_handler=0x00666418, player_card_count=0x00666408),
    "MAGIC": dict(slot=0x006A5F30, master=0x0051AEB8, count=0x006A3F78, objects=0x006FECC0,
                  f_mana=0x00474389, f_clear=0x00474D1E),
}

# Card-table indexes and master-record fields from the doc.
ELVES, BOARS, BEES, FOREST = 56, 61, 323, 2
GREEN = 8  # "+6 the colour byte, 8 = green"; the first five records hold 2, 4, 8, 16, 32 (Forest is 2)


class Snapshot:
    """Bytes by address; emitted as regions (dwords where aligned)."""

    def __init__(self):
        self.b = {}

    def u8(self, addr, v):
        self.b[addr] = v & 0xFF

    def u16(self, addr, v):
        for i in range(2):
            self.b[addr + i] = (v >> (8 * i)) & 0xFF

    def u32(self, addr, v):
        for i in range(4):
            self.b[addr + i] = (v >> (8 * i)) & 0xFF

    def zeros(self, addr, n):
        for i in range(n):
            self.b.setdefault(addr + i, 0)

    def regions(self):
        out, run = [], []
        for a in sorted(self.b):
            if run and a != run[-1] + 1:
                out.append(run)
                run = []
            run.append(a)
        if run:
            out.append(run)
        regions = []
        for r in out:
            data = bytes(self.b[a] for a in r)
            if r[0] % 4 == 0 and len(data) % 4 == 0:
                regions.append({"addr": f"0x{r[0]:08x}",
                                "dwords": [f"0x{int.from_bytes(data[i:i + 4], 'little'):08x}"
                                           for i in range(0, len(data), 4)]})
            else:
                regions.append({"addr": f"0x{r[0]:08x}", "bytes": data.hex()})
        return regions


def slot(L, player, s, off=0):
    return L["slot"] + player * 0x5B20 + s * 0x120 + off


def master(L, index, off=0):
    return L["master"] + index * 0x34 + off


def write(name, vector):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"doc_{name}.json"), "w", encoding="utf-8") as f:
        json.dump(vector, f, indent=2)
        f.write("\n")


def vector(fn, program, address, description, source, args, ret, mem_in, mem_out, calls=()):
    return {
        "function": fn, "program": program, "address": f"0x{address:08x}",
        "description": description, "source": source,
        "args": args, "expected_return": ret,
        "memory_in": mem_in.regions(), "calls": list(calls),
        "memory_out_expected": mem_out.regions(), "memory_out_exhaustive": True,
    }


# --------------------------------------------------------------------------------------------------
# Magic_QueryCardAttribute (DUEL.EXE 0x0048b81a)


def query(name, card, printed, code, expected, description, recompute_bit=0, cache=None,
          modifier=0, extra_in=None, extra_out=None, source_note=""):
    """Player 0, slot 3, outside any event (depth 0), target slot -1, card untapped."""
    L = LAYOUT["DUEL"]
    s = 3
    mi, mo = Snapshot(), Snapshot()
    mi.u32(L["saved"], 0x1234)            # illustrative: saved on entry, restored on return
    mi.u32(L["counter"], 41)              # illustrative: the query counter
    mi.u32(L["depth"], 0)                 # not inside an event: no context push, no card scan
    mi.u32(slot(L, 0, s, 0x04), card)
    mi.u8(master(L, card, 0x06), printed.get("colour", GREEN))
    mi.u32(slot(L, 0, s, 0x0C), 0x882)    # "0x882 = permanent in play": Card_IsInPlay is true for it, tapped or not
    # Because it is in play, a toughness query (0x33) reads the card's type byte and the slot's damage field.
    mi.u8(master(L, card, 0x04), printed.get("type", 0x01 if card == FOREST else 0x02))
    mi.u16(slot(L, 0, s, 0x10), 0)        # damage field: 0, so the toughness never trips the death check
    abilities2 = recompute_bit << 24
    mi.u32(slot(L, 0, s, 0x3C), abilities2)
    if extra_in:
        extra_in(mi, L, s)
    # Common outputs.
    mo.u32(L["counter"], 42)
    mo.u32(L["src_player"], 0)
    mo.u32(L["src_slot"], s)
    mo.u32(L["card_id"], card)
    mo.u32(L["card_color"], printed.get("colour", GREEN))
    mo.u32(L["target_slot"], 0xFFFFFFFF)
    mo.u32(L["result"], expected)
    if extra_out:
        extra_out(mo, L, s)
    return vector(
        "Magic_QueryCardAttribute", "DUEL", L["f_query"], description,
        f"{DOC}, `Magic_QueryCardAttribute` codes (emulator){source_note}",
        [0, s, code, -1], expected, mi, mo)


def power_inputs(card, power, cache, recompute, modifier=0):
    def extra_in(mi, L, s):
        mi.u16(master(L, card, 0x0A), power)
        mi.u16(slot(L, 0, s, 0x18), modifier)
        if recompute:
            mi.u32(slot(L, 0, s, 0x38), 0)  # abilities1: byte +0x39 bit 0x40 would double the power
        else:
            mi.u16(slot(L, 0, s, 0x14), cache)
    return extra_in


def toughness_inputs(card, toughness, recompute):
    def extra_in(mi, L, s):
        mi.u16(master(L, card, 0x0C), toughness)
        mi.u16(slot(L, 0, s, 0x1A), 0)
    return extra_in


def main(out=None):
    global OUT
    if out:
        OUT = out
    # Code 0x32, cached: nothing marked for recompute, the slot's cached power (1) is returned.
    write("query_power_elves_cached", query(
        "power_elves_cached", ELVES, {}, 0x32, 1,
        "Llanowar Elves, code 0x32 (power): nothing marked for recompute, so the cached power is returned",
        extra_in=power_inputs(ELVES, 1, cache=1, recompute=False),
        extra_out=lambda mo, L, s: mo.u16(slot(L, 0, s, 0x14), 1)))
    # Code 0x32, recompute bit 4 of byte +0x3f: printed power 1 + modifier 0.
    write("query_power_elves_recompute", query(
        "power_elves_recompute", ELVES, {}, 0x32, 1,
        "Llanowar Elves, code 0x32: marked for recompute, printed power 1 + modifier 0",
        recompute_bit=0x04, extra_in=power_inputs(ELVES, 1, cache=0, recompute=True),
        extra_out=lambda mo, L, s: (mo.u32(slot(L, 0, s, 0x3C), 0), mo.u16(slot(L, 0, s, 0x14), 1))))
    write("query_power_boars_recompute", query(
        "power_boars", BOARS, {}, 0x32, 4,
        "Durkwood Boars, code 0x32: printed power 4",
        recompute_bit=0x04, extra_in=power_inputs(BOARS, 4, cache=0, recompute=True),
        extra_out=lambda mo, L, s: (mo.u32(slot(L, 0, s, 0x3C), 0), mo.u16(slot(L, 0, s, 0x14), 4))))
    # Code 0x33 on Elves: printed toughness 1 (recompute bit 2).
    write("query_toughness_elves_recompute", query(
        "toughness_elves", ELVES, {}, 0x33, 1,
        "Llanowar Elves, code 0x33 (toughness): printed toughness 1",
        recompute_bit=0x02, extra_in=toughness_inputs(ELVES, 1, recompute=True),
        extra_out=lambda mo, L, s: (mo.u32(slot(L, 0, s, 0x3C), 0), mo.u16(slot(L, 0, s, 0x16), 1))))
    # Code 0x34 on Killer Bees: printed ability dword 0x20 (the only printed ability in the game).

    def bees_in(mi, L, s):
        mi.u32(master(L, BEES, 0x14), 0x20)

    write("query_abilities_bees_recompute", query(
        "abilities_bees", BEES, {}, 0x34, 0x20,
        "Killer Bees, code 0x34 (ability bitmask): printed abilities 0x20, not a colour-keyed bit",
        recompute_bit=0x08, extra_in=bees_in,
        extra_out=lambda mo, L, s: mo.u32(slot(L, 0, s, 0x3C), 0x20)))

    # Code 0x3c: the card's current card-table index. Not a token (index below the token range),
    # not marked for restore, so the slot's own index comes back and the colour byte is refreshed.
    def index_query(card, name, card_id):
        def extra_in(mi, L, s):
            mi.u32(L["token_base"], 0x1B0)                 # illustrative: first token index
            mi.u32(slot(L, 0, s, 0x00), card)               # original card: the same card
            mi.u8(master(L, card, 0x19), 0x10 if card == FOREST or card == ELVES else 0)
            if card in (FOREST, ELVES):
                mi.u32(master(L, card, 0x00), card_id)      # illustrative card id (not a special one)
            mi.u8(slot(L, 0, s, 0x38), 0)                   # abilities1 bit 0x40 clear
            mi.u8(slot(L, 0, s, 0x1C), 0)

        def extra_out(mo, L, s):
            mo.u8(slot(L, 0, s, 0x1C), GREEN)               # refreshed from the master colour byte

        return query(name, card, {}, 0x3C, card, f"{name}, code 0x3c (card-table index): returns {card}",
                     extra_in=extra_in, extra_out=extra_out,
                     source_note="; the card ids at record +0 are illustrative")

    write("query_index_forest", index_query(FOREST, "Forest", 0x40))
    write("query_index_elves", index_query(ELVES, "Llanowar Elves", 0x41))

    # Codes 0x35 and 0x36 are not implemented natively (never seen called).
    v = query("code35", ELVES, {}, 0x35, 0, "Code 0x35 (the slot's own power field) is not implemented: "
              "the runner reports UNIMPLEMENTED")
    v["calls"] = []
    v["memory_out_expected"] = []
    v["memory_out_exhaustive"] = False
    write("query_code35_unimplemented", v)

    # ---------------------------------------------------------------------------------------------
    # Magic_IsManaSource: master record +0x18 bit 0x1000 set and bit 1 clear.
    for program, card, name, flags, ret in [
            ("DUEL", FOREST, "Forest", 0x1000, 1),
            ("DUEL", ELVES, "Llanowar Elves", 0x1000, 1),
            ("DUEL", BOARS, "Durkwood Boars", 0x0, 0),
            ("DUEL", BEES, "Killer Bees", 0x19, 0),
            ("MAGIC", FOREST, "Forest", 0x1000, 1)]:
        L = LAYOUT[program]
        mi = Snapshot()
        mi.u32(slot(L, 1, 4, 0x04), card)
        mi.u32(master(L, card, 0x18), flags)
        note = "" if program == "DUEL" else " (MAGIC.EXE layout; assumes its card table has the same record)"
        write(f"is_mana_source_{name.lower().replace(' ', '_')}_{program.lower()}", vector(
            "Magic_IsManaSource", program, L["f_mana"],
            f"{name}: record +0x18 = 0x{flags:x}, returns {ret}{note}",
            f"{DOC}, `Magic_IsManaSource` (emulator)", [1, 4], ret, mi, Snapshot()))

    # ---------------------------------------------------------------------------------------------
    # Card_GetColorAndTypeFlags: "green creatures return 0x2000, Forest 0, sorceries 0x102000,
    # Aspect of Wolf 0x22000". The colour-mask lookup and the colour remap are native; the remap byte is given as 0.
    L = LAYOUT["DUEL"]
    for name, card, type_byte, mask, index, ret in [
            ("green_creature_elves", ELVES, 0x02, GREEN, 3, 0x2000),
            ("forest", FOREST, 0x01, 0x01, 0, 0),
            ("green_sorcery", 400, 0x08, GREEN, 3, 0x102000),
            ("aspect_of_wolf", 401, 0x04, GREEN, 3, 0x22000)]:
        mi = Snapshot()
        mi.u32(slot(L, 0, 5, 0x04), card)
        mi.u32(L["stack_card"], 0x1C0)                     # illustrative placeholder card index
        mi.u8(master(L, card, 0x04), type_byte)
        mi.u8(slot(L, 0, 5, 0x1D), mask)
        illustrative = card >= 400 or name == "forest"
        mi.u8(slot(L, 0, 5, 0xF9 + index), 0)               # no colour remap for this index: it comes back unchanged
        write(f"color_type_flags_{name}", vector(
            "Card_GetColorAndTypeFlags", "DUEL", L["f_color"],
            f"{name.replace('_', ' ')}: type byte 0x{type_byte:02x}, colour mask 0x{mask:x}, returns 0x{ret:x}"
            + ("; card index and colour mask are illustrative, the result is the doc's" if illustrative else ""),
            f"{DOC}, spell-chain window family table (`Card_GetColorAndTypeFlags`, synthetic)",
            [0, 5], ret, mi, Snapshot()))


    # ---------------------------------------------------------------------------------------------
    # The two colour-remap lookups (Card_RemapColorIndexF9 / FF): the byte at slot + 0xf9 (or 0xff) + index,
    # as a signed char, if it is non-zero, else the index. No recorded game ever had a non-zero byte (and the
    # FF lookup was never called), so these cases come from the decompiled body, not from a run: synthetic.
    L = LAYOUT["DUEL"]
    for fn, table, key in (("Card_RemapColorIndexF9", 0xF9, "f_remap_f9"), ("Card_RemapColorIndexFF", 0xFF, "f_remap_ff")):
        for label, byte, index, ret in [("no_remap", 0x00, 3, 3), ("remapped", 0x04, 3, 4), ("negative_byte", 0xFF, 2, -1)]:
            mi = Snapshot()
            mi.u8(slot(L, 0, 5, table + index), byte)
            write(f"{fn.lower()}_{label}", vector(
                fn, "DUEL", L[key],
                f"Remap byte at slot + 0x{table:x} + {index} is 0x{byte:02x}: returns {ret}"
                + (" (the index comes back unchanged)" if byte == 0 else " (the byte as a signed char)"),
                f"{DOC}, round 6 (`{fn}`; synthetic, decompiled body)", [0, 5, index], ret, mi, Snapshot()))


    # ---------------------------------------------------------------------------------------------
    # The AI's plan, cases no recorded game reached (synthetic, from the decompiled bodies): the planned-choice
    # peek was never entered (static only), and the cursor-back was entered once.
    L = LAYOUT["DUEL"]
    for label, thinking, cursor, offset, planned, expect_peeked, wrote in [
            ("none_planned_reads_zero", 0, 2, 1, 99, 0, True),
            ("value_passes_through", 0, 2, 0, 5, 5, True),
            ("thinking_does_nothing", 1, 2, 0, 5, None, False)]:
        mi, mo = Snapshot(), Snapshot()
        mi.u32(L["ai"], thinking)
        if not thinking:
            mi.u32(L["ai_cursor"], cursor)
            mi.u32(L["ai_best_choice"] + 4 * (cursor + offset), planned)
            mo.u32(L["ai_peeked"], expect_peeked)
        write(f"ai_peek_planned_choice_{label}", vector(
            "Ai_PeekPlannedChoice", "DUEL", L["f_peek_choice"],
            f"Cursor {cursor}, offset {offset}, planned choice {planned}, thinking {thinking}: "
            + (f"the peeked choice becomes {expect_peeked}" if wrote else "nothing is written; returns 0"),
            f"{DOC}, round 3 (`Ai_PeekPlannedChoice`; never entered live, synthetic, decompiled body)",
            [offset], 0, mi, mo))
    for cursor, expect in ((0, 0), (1, 0), (3, 2)):
        mi, mo = Snapshot(), Snapshot()
        mi.u32(L["ai_cursor"], cursor)
        mo.u32(L["ai_cursor"], expect)
        write(f"ai_plan_cursor_back_from_{cursor}", vector(
            "Ai_PlanCursorBack", "DUEL", L["f_cursor_back"],
            f"Cursor {cursor} goes to {expect} (it never goes below 0)",
            f"{DOC}, round 3 (`Ai_PlanCursorBack`; synthetic, decompiled body)", [], 0, mi, mo))


    # ---------------------------------------------------------------------------------------------
    # Magic_ScanCards branches no recorded game reached (synthetic, from the decompiled body and the disassembly): the
    # turn-start marking path, the global handler, an empty list at a turn start, the variable that leaks out of the loop,
    # and the skip rules. Handler addresses are real DUEL.EXE ones (Forest, Llanowar Elves).
    L = LAYOUT["DUEL"]
    FOREST_H, ELVES_H = 0x0047A2CF, 0x0046388D

    def scan(name, description, event, entries, turn_player, calls_for, global_card=None, check=0, final_flags=None):
        """entries: [(player, slot, card, display_index, flags)] in play order; calls_for: expected calls."""
        mi, mo = Snapshot(), Snapshot()
        mi.u32(L["saved"], 0x1234)
        mi.u32(L["scan_counter"], 7)
        mi.u32(L["scan_depth"], 0)
        mi.u32(L["master_count"], 447)
        mi.u32(L["turn_player"], turn_player)
        mi.u32(L["global_handler"], 0xFFFFFFFF if global_card is None else global_card)
        used = {(p, sl): card for p, sl, card, _, _ in entries}
        for p in range(2):
            for sl in range(0x50):
                mi.u32(slot(L, p, sl, 0x04), used.get((p, sl), 0xFFFFFFFF))
        for i, (p, sl, card, display, flags) in enumerate(entries):
            mi.u32(L["scan_order_p"] + 4 * i, p)
            mi.u32(L["scan_order_s"] + 4 * i, sl)
            mi.u32(slot(L, p, sl, 0x34), display)
            mi.u32(slot(L, p, sl, 0x0C), flags)
            mi.u32(master(L, card, 0x10), ELVES_H if card == ELVES else FOREST_H)
        mi.u32(L["scan_order_p"] + 4 * len(entries), 0xFFFFFFFF)
        if global_card is not None:
            mi.u32(master(L, global_card, 0x10), ELVES_H if global_card == ELVES else FOREST_H)
        # What the scan leaves: the event and counters, the saved word, each player's highest used slot + 1.
        mo.u32(L["scan_event"], event)
        mo.u32(L["scan_counter"], 8)
        mo.u32(L["scan_depth"], 0)
        mo.u32(L["saved"], 0x1234)
        for p in range(2):
            top = [sl + 1 for (pp, sl) in used if pp == p]
            if top:
                mo.u32(L["player_card_count"] + 4 * p, max(top))
        ran = [e for e in entries if e[3] == entries.index(e) and (e[4] & 2 or e[4] & 0x20)]
        if ran:
            last = ran[-1]
            mo.u32(L["scan_current"], last[0] * 0x80 + last[1])
        if final_flags is not None:                       # the marking path: flags | 0x10, and the flag word set to -1
            fp, fs, fv = final_flags
            mo.u32(slot(L, fp, fs, 0x0C), fv)
            mo.u32(L["scan_flag"], 0xFFFFFFFF)
        write(f"scan_{name}", vector("Magic_ScanCards", "DUEL", L["f_scan"], description,
                                     f"{DOC}, round 8 (`Magic_ScanCards`; synthetic, decompiled body and disassembly)",
                                     [event], 0, mi, mo, calls_for))

    def call(addr, name, args, ret=0):
        return {"callee": f"0x{addr:08x}", "name": name, "args": args, "return": ret, "memory_writes": []}

    handler = lambda addr, p, sl, ev: call(addr, "card_handler", [p, sl, ev])
    # 1. Turn start, the turn player's card has flags & 0x14 == 4, the check returns 0: the card is marked (flags |= 0x10,
    #    the flag word set to -1) and the card event 0x81 is broadcast; then the combat damage step runs.
    scan("turn_start_marks_card", "Event 0x15, turn player 0, a card with flags 0x6: the check returns 0, so it is marked "
         "(flags 0x16, flag word -1) and 0x81 is broadcast, then the combat damage step runs",
         0x15, [(0, 0, FOREST, 0, 0x6)], 0,
         [handler(FOREST_H, 0, 0, 0x15), call(L["c_scan_check"], "scan_check", [0, 0], 0),
          call(L["c_broadcast"], "Magic_BroadcastCardEvent", [0, 0, 0x81]), call(L["c_combat"], "combat_damage_step", [])],
         final_flags=(0, 0, 0x16))
    # 2. The same, but the check returns non-zero: no marking, no broadcast (the combat step still runs).
    scan("turn_start_check_blocks_mark", "As above but the check returns 1: the card is not marked and nothing is broadcast",
         0x15, [(0, 0, FOREST, 0, 0x6)], 0,
         [handler(FOREST_H, 0, 0, 0x15), call(L["c_scan_check"], "scan_check", [0, 0], 1), call(L["c_combat"], "combat_damage_step", [])])
    # 3. The global handler runs after every scan, even of an empty list, with (0, 0x4e, event).
    scan("global_handler_runs", "An empty play order and a global handler card (Llanowar Elves' record): its handler is called "
         "with (0, 0x4e, event) after the scan", 0x32, [], 0, [handler(ELVES_H, 0, 0x4e, 0x32)], global_card=ELVES)
    # 4. Event 0x15 over an empty list: the leaked loop variable is 2, which is nobody's turn, so no combat step.
    scan("turn_start_empty_list_no_combat_step", "Event 0x15, empty play order, turn player 0: the leaked loop variable is 2, "
         "not the turn player, so the combat damage step is not run", 0x15, [], 0, [])
    # 5. The leaked variable comes from the last entry examined even if it was skipped: entry 1 is player 1's but its
    #    display index does not match, so no handler runs for it, yet the turn-player test (player 1) passes.
    scan("leaked_player_from_skipped_entry", "Event 0x15, turn player 1: entry 1 (player 1) is skipped (display index 9), "
         "but its player still reaches the turn-player test, so the combat damage step runs",
         0x15, [(0, 0, FOREST, 0, 0x2), (1, 3, FOREST, 9, 0x2)], 1,
         [handler(FOREST_H, 0, 0, 0x15), call(L["c_combat"], "combat_damage_step", [])])
    # 6. The skip rules: a card in the hand (neither bit 0x2 nor 0x20) is skipped, a card with only bit 0x20 runs.
    scan("skip_rules", "Event 0x32: entry 0 has flags 0x1 (in hand) and is skipped; entry 1 has only bit 0x20 and runs",
         0x32, [(0, 0, FOREST, 0, 0x1), (0, 1, ELVES, 1, 0x20)], 0, [handler(ELVES_H, 0, 1, 0x32)])

    # ---------------------------------------------------------------------------------------------
    # Spell stack (DUEL.EXE). "Play a Forest: PushSpellStack(0, 2, 113, 0, 0)", "Cast Llanowar Elves,
    # pay with the Forest: PushSpellStack(0, 0, 113, 0, 0) when announced, then PushSpellStack(0, 2,
    # 114, 0, 0)". Outside any step (step code -1) and not while the AI thinks.
    def push(name, player, s, card, event, count_before, description, ai=0, step=-1):
        L = LAYOUT["DUEL"]
        mi, mo = Snapshot(), Snapshot()
        mi.u32(L["count"], count_before)
        mi.u32(slot(L, player, s, 0x04), card)
        mi.u8(slot(L, player, s, 0x12), 0)
        mi.u32(slot(L, player, s, 0x28), 0xFFFFFFFF)       # illustrative
        mi.u32(L["cur_step"], step & 0xFFFFFFFF)
        mi.u32(L["step_fallback"], 7)                      # illustrative
        mi.u32(L["ai"], ai)
        mo.u32(L["entries"] + 4 * count_before, card | event << 16)
        mo.u32(L["objects"] + 8 * count_before, player)
        mo.u32(L["objects"] + 8 * count_before + 4, s)
        mo.u32(L["aux"] + 8 * count_before, 0)
        mo.u32(L["aux"] + 8 * count_before + 4, 0xFFFFFFFF)
        mo.u32(L["step"] + 4 * count_before, 7 if step == -1 else step)
        if ai != 1:
            mo.u32(L["flags"] + 4 * count_before, 0)
        mo.u32(L["count"], count_before + 1)
        mo.u32(L["objects"] + 8 * (count_before + 1), 0xFFFFFFFF)
        write(name, vector("Magic_PushSpellStack", "DUEL", L["f_push"], description,
                           f"{DOC}, live results from the in-process emulator (`DUEL.EXE`)",
                           [player, s, event, 0, 0], 0, mi, mo))

    push("push_play_forest", 0, 2, FOREST, 0x71, 0, "Play a Forest: PushSpellStack(0, 2, 113, 0, 0) on an empty stack")
    push("push_announce_elves", 0, 0, ELVES, 0x71, 0,
         "Cast Llanowar Elves, announce: PushSpellStack(0, 0, 113, 0, 0); 0x71 keeps the card itself as the object")
    push("push_pay_with_forest", 0, 2, FOREST, 0x72, 1,
         "Pay for the Elves with the Forest: PushSpellStack(0, 2, 114, 0, 0) on top; card index 2 < 5, no stand-in")
    push("push_while_ai_thinks", 0, 2, FOREST, 0x71, 0,
         "The same push while g_IsAiThinking is 1: the flags entry is not written (illustrative)", ai=1)

    # A stand-in object (synthetic: event 0x72 on a non-land card). The free-slot finder is replayed.
    L = LAYOUT["DUEL"]
    mi, mo = Snapshot(), Snapshot()
    src, new = 0, 7
    mi.u32(L["count"], 1)
    mi.zeros(slot(L, 0, src), 0x120)
    mi.u32(slot(L, 0, src, 0x00), ELVES)
    mi.u32(slot(L, 0, src, 0x04), ELVES)
    mi.u32(slot(L, 0, src, 0x0C), 0x882)
    mi.u32(slot(L, 0, src, 0x44), 0x55)
    mi.u32(slot(L, 0, src, 0x50), 0x66)
    mi.u8(slot(L, 0, src, 0x20), 0x77)
    mi.u32(L["stack_card"], 0x1C0)
    mi.u32(slot(L, 0, new, 0x34), 0x99)                   # the new slot's display index survives
    mi.u32(L["cur_step"], 0xD3)                           # inside the "Casting" step
    mi.u32(L["ai"], 0)
    mo.u32(L["entries"] + 4, ELVES | 0x72 << 16)
    for off in range(0, 0x120, 4):                         # the copy of slot 0 ...
        mo.u32(slot(L, 0, new, off), int.from_bytes(bytes(mi.b[slot(L, 0, src, off) + i] for i in range(4)), "little"))
    mo.u32(slot(L, 0, new, 0x04), 0x1C0)                   # ... holding the placeholder card
    mo.u32(slot(L, 0, new, 0x50), 0)
    mo.u8(slot(L, 0, new, 0x20), 0)
    mo.u32(slot(L, 0, new, 0x00), ELVES)                   # the card it stands for
    mo.u32(slot(L, 0, new, 0x0C), 0x882)                   # | 2, already set
    mo.u32(slot(L, 0, new, 0xF0), 0)
    mo.u32(slot(L, 0, new, 0xF4), src)
    mo.u32(slot(L, 0, new, 0x34), 0x99)
    mo.u32(L["objects"] + 8, 0)
    mo.u32(L["objects"] + 12, new)
    mo.u32(L["aux"] + 8, 0)
    mo.u32(L["aux"] + 12, 0)
    mo.u32(L["step"] + 4, 0xD3)
    mo.u32(L["flags"] + 4, 0)
    mo.u32(L["count"], 2)
    mo.u32(L["objects"] + 16, 0xFFFFFFFF)
    write("push_stand_in_object", vector(
        "Magic_PushSpellStack", "DUEL", L["f_push"],
        "Event 0x72 on Llanowar Elves (index 56 >= 5): a stand-in object is made in the slot the finder returns "
        "(synthetic; values illustrative)",
        f"{DOC}, the spell stack table (`Magic_PushSpellStack`); decompiled body", [0, src, 0x72, 0, 0], 0, mi, mo,
        calls=[{"callee": f"0x{L['c_find_free']:08x}", "name": "Pic_Subsystem_00451291", "args": [0, 0x1C0],
                "return": new}]))

    # Drop: "decrements the count, clears the stand-in slot if its card id is the placeholder, and writes
    # the -1 sentinel".
    mi, mo = Snapshot(), Snapshot()
    mi.u32(L["count"], 2)
    mi.u32(L["objects"] + 8, 0)
    mi.u32(L["objects"] + 12, 7)
    mi.u32(L["stack_card"], 0x1C0)
    mi.u32(slot(L, 0, 7, 0x04), 0x1C0)
    mo.u32(L["count"], 1)
    mo.u32(slot(L, 0, 7, 0x04), 0xFFFFFFFF)
    mo.u32(L["objects"] + 8, 0xFFFFFFFF)
    write("drop_stand_in", vector(
        "Magic_DropTopSpell", "DUEL", L["f_drop"],
        "Drop a stand-in object on top of a two-entry stack: its slot is freed (the AI abandoning a cast)",
        f"{DOC}, round 2 (`Magic_DropTopSpell`)", [], 0, mi, mo))

    mi, mo = Snapshot(), Snapshot()
    mi.u32(L["count"], 1)
    mi.u32(L["objects"], 0)
    mi.u32(L["objects"] + 4, 2)
    mi.u32(L["stack_card"], 0x1C0)
    mi.u32(slot(L, 0, 2, 0x04), FOREST)
    mo.u32(L["count"], 0)
    mo.u32(L["objects"], 0xFFFFFFFF)
    write("drop_real_card", vector(
        "Magic_DropTopSpell", "DUEL", L["f_drop"],
        "Drop the announced Forest: the slot keeps its card, only the entry goes", f"{DOC}, round 2",
        [], 0, mi, mo))

    mi = Snapshot()
    mi.u32(L["count"], 0)
    write("drop_empty", vector(
        "Magic_DropTopSpell", "DUEL", L["f_drop"], "Drop on an empty stack changes nothing", f"{DOC}, round 2",
        [], 0, mi, Snapshot()))

    # Clear: "sets the count to 0 and the first object to -1"; seen once at the start of every turn.
    for program in ("DUEL", "MAGIC"):
        L = LAYOUT[program]
        mi, mo = Snapshot(), Snapshot()
        mo.u32(L["count"], 0)
        mo.u32(L["objects"], 0xFFFFFFFF)
        write(f"clear_{program.lower()}", vector(
            "Magic_ClearSpellStack", program, L["f_clear"],
            f"Start of a turn: count 0 and the object list terminated ({program}.EXE layout)",
            f"{DOC}, the spell stack", [], 0, mi, mo))


    # ---------------------------------------------------------------------------------------------
    # Crt_Memcpy (DUEL.EXE 0x004d99b0): the C runtime's memcpy, which copies backwards when the destination lies inside the
    # source, so it behaves as memmove. The expected bytes are what memmove gives, worked out here, not run.
    BUF = 0x00700000
    for name, dst, src, n, why in (
            ("zero_length", BUF + 0x40, BUF, 0, "no bytes: nothing changes, the destination is returned"),
            ("aligned_words", BUF + 0x40, BUF, 16, "four whole dwords between aligned buffers"),
            ("tail_of_three", BUF + 0x40, BUF, 7, "one dword and a three-byte tail"),
            ("unaligned_destination", BUF + 0x41, BUF, 33, "a destination that is not dword aligned: head bytes, words, tail"),
            ("overlap_forward", BUF, BUF + 5, 40, "destination below the source, overlapping: copied forwards"),
            ("overlap_backward", BUF + 5, BUF, 40, "destination inside the source: copied backwards, so the source survives intact"),
            ("overlap_backward_aligned", BUF + 8, BUF, 24, "overlapping backwards, aligned end"),
            ("short_unaligned", BUF + 0x43, BUF + 2, 9, "nine bytes to an odd destination: a byte-wise copy")):
        data = bytes((7 * i + 3) & 0xFF for i in range(0x60))
        mi, mo = Snapshot(), Snapshot()
        for i, b in enumerate(data):
            mi.u8(BUF + i, b)
        image = bytearray(data)
        image[dst - BUF:dst - BUF + n] = data[src - BUF:src - BUF + n]
        for i in range(n):
            mo.u8(dst + i, image[dst - BUF + i])
        write(f"crt_memcpy_{name}", vector(
            "Crt_Memcpy", "DUEL", 0x004D99B0, f"{n} bytes from +{src - BUF:#x} to +{dst - BUF:#x}: {why}",
            "the C runtime's memcpy (a memmove), expected bytes by definition", [dst, src, n], dst, mi, mo))


if __name__ == "__main__":
    main()
