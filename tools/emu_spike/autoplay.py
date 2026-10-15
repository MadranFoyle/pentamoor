"""
A duel autopilot that plays the game: lands, creatures, attacks, blocks. For live_drive.py's `duel:SECS` and for soak runs.

It reads the duel from the emulator's host-side state only (the card windows, their slot records in guest memory, the prompt bar's text),
and acts through real mouse events like the person at the keyboard. The card facts (cost, type, power, toughness) are from the game's own
INFO.CSV; a card is found by the short name the game keeps in its master card table.

What it does, per turn:
  - plays a land (preferring the colour its hand needs), then casts creatures and mana-free artifacts it can pay for, most expensive first
    (it taps basic lands for the colours needed, then for the rest; a card that does not leave the hand is not tried again that turn)
  - attacks with creatures that came in on an earlier turn when the attack looks safe (no untapped blocker of theirs could kill it and
    survive, or they have no blockers; flyers when they have no flyers)
  - blocks when a block kills the attacker or survives, or when the damage would otherwise be lethal
  - answers the coin toss, the start-of-duel and discard prompts, and presses Done through everything else
It does not cast instants, sorceries, auras or anything that asks for a target.
"""
import csv
import os
import re
import time

from winemu import duelview, user32

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INFO = os.path.join(ROOT, "sources", "installed", "Magic", "Program", "INFO.CSV")
MASTER = os.path.join(ROOT, "sources", "installed", "Magic", "Program", "MASTER.CSV")           # the rules text, for the abilities
LANDS = {"plains": "W", "island": "U", "swamp": "B", "mountain": "R", "forest": "G"}
MANA_CREATURES = {"llanowar elves": "G", "sisters of the flame": "R", "fyndhorn elves": "G"}          # creatures that tap for one mana of a colour
COLOURS = "BGRWU"                                                  # the order of the first five digits of a card's mana cost in INFO.CSV


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def classify(card):
    """(role, damage) of a card from its type and rules text. Roles: creature; burn (damage to a creature: damage N); buff (an aura that
    helps the creature it is on); curse (an aura or spell that hurts the other side's creature or its controller); other (not played)."""
    t, text = card["type"], card["text"]
    if t.startswith("Summon") or (t == "Artifact" and card["power"] > 0):
        return "creature", 0
    body = " ".join(text.split())
    if t in ("Instant", "Sorcery", "Interrupt"):
        m = re.search(r"deals (\d+) damage to target creature", body)
        if m and "x" not in body.lower().split("damage")[0][-12:].split():
            return "burn", int(m.group(1))
        if re.search(r"(destroy|bury|remove) target (non-?\w+,? )*creature", body.lower()):
            return "burn", 99
        return "other", 0
    if t.startswith("Enchant") and "target creature" in body.lower() or t.startswith("Enchant") and "enchanted creature" in body.lower():
        low = body.lower()
        if "controller" in low or re.search(r"(gets|gains?) -|cannot attack|can't attack|cannot block|can't block|deals \d+ damage to target creature's", low):
            return "curse", 0
        if re.search(r"(gets|gains?) \+|gains? (flying|first strike|trample|banding|regenerat)|has (flying|first strike)", low):
            return "buff", 0
    return "other", 0


class Facts:
    """name -> dict(type, cost {colour: n, 'any': n}, power, toughness, flying) from INFO.CSV, with prefix lookup for short names."""

    def __init__(self, path=INFO):
        self.by_name = {}
        self.by_id = {}
        self.names = []
        rules = {}
        try:
            with open(MASTER, newline="", encoding="latin-1") as fh:
                for row in csv.DictReader(fh):
                    rules[int(row["ID"])] = (row.get("Rule Text") or "").lower()
        except (OSError, ValueError, KeyError):
            pass
        with open(path, newline="", encoding="latin-1") as fh:
            for row in csv.DictReader(fh):
                digits = re.sub(r"[^0-9]", "0", (row.get("Mana Costs") or "000000").strip()).rjust(6, "0")
                cost = {c: int(digits[i]) for i, c in enumerate(COLOURS)}
                cost["any"] = int(digits[5])
                def num(v):
                    return int(v) if (v or "").strip().isdigit() else 0
                text = rules.get(int(row["ID"]), "") if (row.get("ID") or "").strip().isdigit() else ""
                card = dict(name=row["Card Name"].strip(), type=(row.get("Type") or "").strip(), cost=cost,
                            power=num(row.get("Pow")), toughness=num(row.get("Tuff")), cmc=sum(cost.values()),
                            flying="flying" in text, text=text)
                card["role"], card["damage"] = classify(card)
                if (row.get("ID") or "").strip().isdigit():
                    self.by_id[int(row["ID"])] = card
                for key in (norm(row["Card Name"]), norm(row.get("Short Name") or "")):
                    if key and key not in self.by_name:
                        self.by_name[key] = card
                        self.names.append(key)

    def find(self, short):
        k = norm(short)
        if k in self.by_name:
            return self.by_name[k]
        hits = [n for n in self.names if n.startswith(k)] if len(k) >= 4 else []
        return self.by_name[hits[0]] if hits else None


def master_id(m, cid):
    """The card's number in INFO.CSV, which the master card table keeps at offset 0x10."""
    return m.r32(duelview.TYPE_TABLE + cid * duelview.TYPE_SIZE + 0x10)


def master_name(m, cid):
    raw = bytes(m.rd(duelview.TYPE_TABLE + cid * duelview.TYPE_SIZE + 1, 15))
    return raw.split(b"\0")[0].decode("latin-1")


def _signed(v):
    return v - (1 << 32) if v >= 1 << 31 else v


class Autoplay:
    def __init__(self, m, click_at, log, facts=None, shot=None):
        self.m, self.click_at, self.log = m, click_at, log
        self.shot = shot or (lambda name: None)
        self.facts = facts or Facts()
        self.last_life = (10, 10)
        self.reset_turn()
        self.seen_before = set()                                   # my creature slots that were on the battlefield at an earlier main phase
        self.failed = set()                                        # (turn, name) casts that did not work

    def reset_turn(self):
        self.land_played = False
        self.attacked = False
        self.blocked = False
        self.cast_done = False

    # ---- reading the screen -----------------------------------------------------------------------------
    def windows(self):
        return list(self.m.state.get("u32", {}).get("windows", {}).values())

    def prompt(self):
        for w in self.windows():
            if w["cls"] == "MAGIC_TellUserClass" and w["visible"]:
                return w
        return None

    def cards(self):
        out = []
        wins = self.m.state["u32"]["windows"]
        for c in duelview.cards(self.m):
            w = wins.get(c["h"])
            if w is None:
                continue
            c["name"] = master_name(self.m, c["cid"]) if 0 <= c["cid"] < 2000 else "?"
            c["fact"] = self.facts.by_id.get(master_id(self.m, c["cid"])) if 0 <= c["cid"] < 2000 else None
            if c["fact"] is None:
                c["fact"] = self.facts.find(c["name"])
            else:
                c["name"] = c["fact"]["name"]
            c["rect"] = user32.abs_rect(self.m, w)
            c["tapped"] = bool(c["flags"] & 0x10)
            out.append(c)
        return out

    def cards_by_slot(self, player, slot):
        return next((c for c in self.cards() if c["player"] == player and c["slot"] == slot), None)

    def hand(self, cards):
        h = [c for c in cards if c["player"] == 0 and c["parent"].lower().startswith("your hand")]
        return sorted(h, key=lambda c: c["rect"][1])

    def mine(self, cards):
        return [c for c in cards if c["player"] == 0 and c["parent"].lower().startswith("player territory")]

    def theirs(self, cards):
        return [c for c in cards if c["player"] == 1 and not c["parent"].lower().startswith("opponent (")]

    @staticmethod
    def is_land(c):
        return c["name"].lower() in LANDS or (c["fact"] is not None and c["fact"]["type"] == "Land")

    @staticmethod
    def is_creature(c):
        return c["fact"] is not None and c["fact"]["type"].startswith("Summon")

    def click_card(self, c, dy=None):
        x0, y0, x1, y1 = c["rect"]
        self.click_at((x0 + x1) // 2, (y0 + 4) if dy is None else (y0 + dy))

    # ---- main phase ---------------------------------------------------------------------------------------
    @staticmethod
    def source_colour(c):
        n = c["name"].lower()
        return LANDS.get(n) or MANA_CREATURES.get(n)

    def pay_plan(self, fact, sources):
        """The untapped mana sources (basic lands, then mana creatures) to tap for a card, or None if they cannot pay for it. Lands are
        preferred for the generic part so that the creatures stay untapped."""
        need = {c: fact["cost"][c] for c in COLOURS}
        free = sorted(sources, key=lambda c: c["name"].lower() not in LANDS)                  # lands first
        chosen = []
        for col in COLOURS:
            for _ in range(need[col]):
                src = next((l for l in free if self.source_colour(l) == col), None)
                if src is None:
                    return None
                free.remove(src)
                chosen.append(src)
        if len(free) < fact["cost"]["any"]:
            return None
        return chosen + free[:fact["cost"]["any"]]

    def mana_sources(self, cards):
        mine = self.mine(cards)
        out = [c for c in mine if self.is_land(c) and not c["tapped"] and c["name"].lower() in LANDS]
        out += [c for c in mine if c["name"].lower() in MANA_CREATURES and not c["tapped"] and c["slot"] in self.seen_before]
        return out

    def best_set(self, spells, sources):
        """The subset of `spells` (each (spell, target)) that uses the most mana, creatures preferred on a tie, paid from `sources` in turn."""
        best, best_key = [], (0, 0)
        n = len(spells)
        for mask in range(1, 1 << n):
            pick = [spells[i] for i in range(n) if mask >> i & 1]
            free, ok = list(sources), True
            for sp, _ in sorted(pick, key=lambda x: -sum(1 for c in COLOURS if x[0]["fact"]["cost"][c])):
                plan = self.pay_plan(sp["fact"], free)
                if plan is None:
                    ok = False
                    break
                for src in plan:
                    free.remove(src)
            if ok:
                key = (sum(sp["fact"]["cmc"] for sp, _ in pick), sum(1 for sp, _ in pick if sp["fact"]["role"] == "creature"))
                if key > best_key:
                    best, best_key = pick, key
        return best

    def main_phase(self, turn):
        m = self.m
        cards = self.cards()
        hand = self.hand(cards)
        if not self.land_played:
            lands = [c for c in hand if self.is_land(c)]
            if lands:
                pick = lands[0]
                spells = [c for c in hand if not self.is_land(c) and c["fact"]]
                want = {col for s in spells for col in COLOURS if s["fact"]["cost"][col]}
                have = {LANDS.get(c["name"].lower()) for c in self.mine(cards) if self.is_land(c)}
                pick = next((l for l in lands if LANDS.get(l["name"].lower()) in want - have), pick)
                self.log(f"land {pick['name']}")
                self.click_card(pick)
                self.land_played = True
                time.sleep(1.5)
                cards = self.cards()
                hand = self.hand(cards)
        cands = []
        for c in hand:
            if not c["fact"] or c["fact"]["role"] == "other" or (turn, c["name"]) in self.failed:
                continue
            target = None
            if c["fact"]["role"] != "creature":
                target = self.pick_target(c, cards)
                if target is None:
                    continue
            cands.append((c, target))
        cands = cands[:8]
        for s, target in self.best_set(cands, self.mana_sources(cards)):
            cards = self.cards()
            plan = self.pay_plan(s["fact"], self.mana_sources(cards))
            if plan is None:
                continue
            hand_before = len(self.hand(cards))
            self.log(f"cast {s['name']} ({s['fact']['role']}, cost {s['fact']['cmc']})"
                     + (f" on {target['name']}" if target else "") + f" tapping {[l['name'] for l in plan]}")
            for land in plan:
                self.click_card(land, dy=40)
                time.sleep(0.8)
            now = {c["slot"]: c for c in self.hand(self.cards())}
            spell = next((c for c in now.values() if c["cid"] == s["cid"]), None)
            if spell is not None:
                self.click_card(spell)
                time.sleep(2.0)
            if target is not None:
                self.aim(s, target)
            time.sleep(1.0)
            if len(self.hand(self.cards())) >= hand_before:
                self.failed.add((turn, s["name"]))
                self.log(f"{s['name']} did not leave the hand")
        self.cast_done = True

    def pick_target(self, s, cards):
        """The creature a spell is for, or None if there is nothing worth it."""
        role, dmg = s["fact"]["role"], s["fact"]["damage"]
        mine = [c for c in self.mine(cards) if self.is_creature(c)]
        theirs = [c for c in self.theirs(cards) if self.is_creature(c) and c["fact"]]
        if role == "burn":
            kill = [c for c in theirs if c["fact"]["toughness"] <= dmg]
            return max(kill, key=lambda c: c["fact"]["cmc"], default=None) if kill and max(c["fact"]["cmc"] for c in kill) >= s["fact"]["cmc"] - 1 else None
        if role == "buff":
            return max(mine, key=lambda c: (c["fact"]["power"], c["fact"]["toughness"]), default=None)
        if role == "curse":
            return max(theirs, key=lambda c: c["fact"]["power"], default=None)
        return None

    def aim(self, s, target):
        """After a spell asks for a target ('Select target creature.'), click it; cancel if the prompt is something else."""
        for _ in range(6):
            time.sleep(0.8)
            p = self.prompt()
            title = (p["title"] if p else "") or ""
            if title.startswith("Select target creature") or title.startswith("Select target"):
                break
        else:
            return
        if not title.startswith("Select target creature"):
            self.log(f"{s['name']} wants {title!r}: cancelled")
            btn = next((w for w in self.windows() if str(w["cls"]).upper() == "BUTTON" and w["visible"] and p and w["parent"] == p["hwnd"]), None)
            if btn:
                x0, y0, x1, y1 = user32.abs_rect(self.m, btn)
                self.click_at((x0 + x1) // 2, (y0 + y1) // 2)
            return
        t = self.cards_by_slot(target["player"], target["slot"])
        if t is not None:
            self.click_card(t, dy=40)
            time.sleep(2.0)

    # ---- combat -------------------------------------------------------------------------------------------
    def attack(self):
        """Attack with creatures that can, as many as is safe: what is left at home plus my life must withstand their whole side next turn
        (each blocker stops one attacker, the biggest first), unless the attack is lethal now."""
        cards = self.cards()
        mine = [c for c in self.mine(cards) if self.is_creature(c) and not c["tapped"] and c["slot"] in self.seen_before and c["fact"]["power"] > 0]
        their_creatures = [c for c in self.theirs(cards) if self.is_creature(c) and c["fact"]]
        blockers = [c for c in their_creatures if not c["tapped"]]
        life, their_life = self.m.r32(0x6A3F7C), self.m.r32(0x6FF194)
        all_mine = [c for c in self.mine(cards) if self.is_creature(c)]
        powers = sorted((c["fact"]["power"] for c in their_creatures), reverse=True)

        def exposed(home):
            """damage that gets through if `home` (my creatures) stay back to block"""
            return sum(powers[len(home):])

        # attackers that would just die to a blocker are left out
        def can_block(b, a):
            return b["fact"]["flying"] or not a["fact"]["flying"]
        cand = [c for c in mine if not any(can_block(b, c) and b["fact"]["power"] >= c["fact"]["toughness"] and b["fact"]["toughness"] > c["fact"]["power"]
                                           for b in blockers)]
        cand.sort(key=lambda c: -c["fact"]["power"])
        lethal = sum(c["fact"]["power"] for c in cand if not any(can_block(b, c) for b in blockers)) >= their_life
        while cand and not lethal:
            home = [c for c in all_mine if c not in cand]
            if life - exposed(home) >= 4:
                break
            cand.pop()                                              # keep the strongest attacking, the weakest home
        self.log(f"attack plan: life {life}/{their_life}, their power {powers}, attackers {[c['name'] for c in cand]} of {[c['name'] for c in mine]}")
        for c in cand:
            self.log(f"attack with {c['name']}")
            self.click_card(c, dy=40)
            time.sleep(1.0)

    def block(self):
        cards = self.cards()
        attackers = [c for c in self.theirs(cards) if self.is_creature(c) and c["tapped"]]
        mine = [c for c in self.mine(cards) if self.is_creature(c) and not c["tapped"]]
        self.log("block view: attackers " + str([(c["name"], c["fact"]["power"], c["fact"]["toughness"]) for c in attackers])
                 + " mine " + str([(c["name"], c["fact"]["power"], c["fact"]["toughness"]) for c in mine]) + f" life {self.m.r32(0x6A3F7C)}")
        attackers = [a for a in attackers if a["fact"]]
        incoming = sum(a["fact"]["power"] for a in attackers)
        life = self.m.r32(0x6A3F7C)
        lethal = life - incoming <= 2                              # chump blocks when the damage would leave me nearly dead
        used = set()
        for a in sorted(attackers, key=lambda a: -a["fact"]["power"]):
            if a["fact"]["power"] <= 0:
                continue
            best = None
            for b in mine:
                if b["slot"] in used or (a["fact"]["flying"] and not b["fact"]["flying"]):
                    continue
                survives = b["fact"]["toughness"] > a["fact"]["power"]
                kills = b["fact"]["power"] >= a["fact"]["toughness"]
                score = (2 if survives and kills else 1 if survives else 1 if kills and b["fact"]["cmc"] <= a["fact"]["cmc"] else 0)
                if lethal and score == 0:
                    score = 0.5
                if score and (best is None or (score, -b["fact"]["cmc"]) > (best[0], -best[1]["fact"]["cmc"])):
                    best = (score, b)                                # the better block; on a tie the cheaper creature
            if best:
                b = best[1]
                used.add(b["slot"])
                self.log(f"block {a['name']} with {b['name']}")
                self.click_card(b, dy=40)
                time.sleep(1.5)
                self.click_card(self.cards_by_slot(a["player"], a["slot"]), dy=40)
                time.sleep(1.5)

    def assign_damage(self, title):
        """'X: Assign damage to blockers, N points left': click a blocker for each point (the panel lists the blockers on top)."""
        n = int(re.search(r"(\d+) points? left", title).group(1)) if re.search(r"(\d+) points? left", title) else 1
        cards = self.cards()
        blockers = [c for c in cards if c["player"] == 1 and c["parent"].lower().startswith("your attack") and c["rect"][1] < 150 and c["fact"]
                    and self.is_creature(c)]
        if not blockers:
            if not getattr(self, "dmg_logged", False):
                self.dmg_logged = True
                self.log("no blocker found: " + str([(c["name"], c["player"], c["parent"], c["rect"]) for c in cards if c["parent"] and "Territory" not in c["parent"] and "hand" not in c["parent"].lower()]))
                self.shot("damage")
            return
        self.log(f"assign damage: {n} points to {blockers[0]['name']}")
        self.click_card(blockers[0], dy=40)

    # ---- one step of the loop -----------------------------------------------------------------------------
    def step(self, title, turn):
        """Act on the prompt bar's text. Returns True if a click was made that should be given time to take effect."""
        self.last_life = (_signed(self.m.r32(0x6A3F7C)), _signed(self.m.r32(0x6FF194)))
        if title.startswith("Main phase (before"):
            if not self.cast_done:
                self.main_phase(turn)
                return True
        elif title.startswith("Combat phase: Choose attackers"):
            if not self.attacked:
                self.attacked = True
                self.attack()
                return True
        elif title.startswith("Choose blockers"):
            if not self.blocked:
                self.blocked = True
                self.block()
                return True
        elif "Assign damage to blockers" in title:
            self.assign_damage(title)
            return True
        elif title.startswith("Main phase (after") and not self.cast_done:
            self.main_phase(turn)
            return True
        return False

    def watch_life(self):
        self.last_life = (_signed(self.m.r32(0x6A3F7C)), _signed(self.m.r32(0x6FF194)))

    def new_prompt(self, title):
        """Called when the prompt bar's text changes. A new turn starts at the first 'Main phase (before' after anything else."""
        kind = "main1" if title.startswith("Main phase (before") else "other"
        if kind == "main1" and getattr(self, "last_kind", "other") != "main1":
            self.log(f"new turn: life me {self.m.r32(0x6A3F7C)} them {self.m.r32(0x6FF194)}")
            cards = self.cards()
            self.seen_before |= {c["slot"] for c in self.mine(cards)}
            self.reset_turn()
        self.last_kind = kind
