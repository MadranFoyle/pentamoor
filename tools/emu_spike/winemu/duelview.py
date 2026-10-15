"""
What a duel looks like from outside, read from the guest's memory and its windows (host-side reads only: the guest is never touched).

The duel's card windows (class MAGICGAME_CardClass) carry the player (0 me, 1 the opponent) and the slot in their window longs 0 and 4;
the slot's record (0x120 bytes per slot, 0x5B20 per player, from 0x6826C4) names a card type (id into the 0x34-byte table at 0x4FF590),
whose card record (0x98 bytes from 0x618AC4) holds the name. `cards(m)` lists the visible ones with where they are (hand, battlefield),
type bits, the tapped flag. Used by live_drive's autopilot and run.py's script ops.
"""
SLOT_BASE, SLOT_SIZE, PLAYER_SIZE = 0x6A5F34, 0x120, 0x5B20                # g_CardSlot_CardId, per slot, per player (MAGIC.EXE)
TYPE_TABLE, TYPE_SIZE = 0x51AEA8, 0x34                                      # g_MasterCardTable
CARD_TABLE, CARD_SIZE = 0x5224E0, 0x98                                      # Scards, the card database MAGIC.EXE exports to DECKDLL


def slot_addr(player, slot):
    return SLOT_BASE + slot * SLOT_SIZE + player * PLAYER_SIZE


def cards(m):
    wins = m.state.get("u32", {}).get("windows", {})
    out = []
    for h, w in list(wins.items()):
        if w["cls"] != "MAGICGAME_CardClass" or not w["visible"] or w["w"] <= 0:
            continue
        pl, sl = w["extra"].get(0, -1), w["extra"].get(4, -1)
        if pl not in (0, 1) or not 0 <= sl < 80:
            continue
        base = slot_addr(pl, sl)
        cid = m.r32(base)
        try:
            ident = cid
            name = m.cstr(m.r32(CARD_TABLE + cid * CARD_SIZE + 4), 30).decode("latin-1")
            mtype = m.r32(TYPE_TABLE + cid * TYPE_SIZE + 4) & 0xFF
        except Exception:                                          # noqa: BLE001
            ident, name, mtype = -1, "?", 0
        par = wins.get(w["parent"], {})
        out.append(dict(h=h, player=pl, slot=sl, cid=cid, ident=ident, name=name, mtype=mtype, flags=m.r32(base + 8), tap=m.r32(base + 0xEC),
                        parent=par.get("title", ""), rect=None))
    return out


def dump(m, c):
    """The raw dwords of a card's three records, for finding fields."""
    if not 0 <= c["ident"] < 2000 or not 0 <= c["cid"] < 2000:
        return [], [], []
    rec = [m.r32(CARD_TABLE + c["ident"] * CARD_SIZE + 4 * i) for i in range(CARD_SIZE // 4)]
    typ = [m.r32(TYPE_TABLE + c["cid"] * TYPE_SIZE + 4 * i) for i in range(TYPE_SIZE // 4)]
    slot = [m.r32(slot_addr(c["player"], c["slot"]) + 4 * i) for i in range(SLOT_SIZE // 4)]
    return rec, typ, slot
