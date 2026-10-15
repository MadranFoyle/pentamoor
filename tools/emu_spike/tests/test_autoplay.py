"""The duel autopilot's decisions, on fake card data (no emulator)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import autoplay  # noqa: E402


def card(name, ctype="Summon", cost="000000", p=1, t=1, flying=False):
    digits = cost.rjust(6, "0")
    c = {col: int(digits[i]) for i, col in enumerate(autoplay.COLOURS)}
    c["any"] = int(digits[5])
    return dict(name=name, type=ctype, cost=c, power=p, toughness=t, cmc=sum(c.values()), flying=flying, text="")


def land(name):
    return dict(name=name, fact=dict(type="Land"), tapped=False, slot=0, player=0, parent="Player Territory", rect=(0, 0, 80, 80), cid=1, flags=0)


@pytest.fixture
def ap():
    a = autoplay.Autoplay.__new__(autoplay.Autoplay)
    a.facts = None
    a.log = lambda *x: None
    return a


def test_cost_digits_of_info_csv_are_five_colours_then_generic():
    if not os.path.exists(autoplay.INFO):
        pytest.skip("no game data")
    f = autoplay.Facts()
    falcon = f.find("Zephyr Falcon")                                                   # 000011: one blue, one generic
    assert falcon["cost"]["U"] == 1 and falcon["cost"]["any"] == 1 and falcon["cmc"] == 2
    assert falcon["type"] == "Summon" and (falcon["power"], falcon["toughness"]) == (1, 1)
    assert f.by_id[841]["name"] == "Wall of Dust"                                      # the master card table keeps this number
    assert f.find("Zephyr Falcon")["flying"] and not f.find("Craw Wurm")["flying"]


def test_pay_plan_taps_the_colours_first_then_any_land(ap):
    lands = [land("Island"), land("Mountain"), land("Forest")]
    plan = ap.pay_plan(card("Falcon", cost="000011"), lands)                           # U + 1
    assert [l["name"] for l in plan][0] == "Island" and len(plan) == 2
    assert ap.pay_plan(card("Fire", cost="000300"), lands) is None                     # RRR: only one Mountain
    assert ap.pay_plan(card("Big", cost="000005"), lands) is None                      # 5 generic with 3 lands
    assert ap.pay_plan(card("Free"), lands) == []                                      # costs nothing


def test_names_are_matched_loosely():
    assert autoplay.norm("Tawnos's Wand") == "tawnosswand"
    assert autoplay.norm("Fire Elem.") == "fireelem"


def test_spells_are_classified_from_their_rules_text():
    def role(ctype, text, p=0):
        c = dict(type=ctype, text=text, power=p)
        return autoplay.classify(c)
    assert role("Summon", "", 2)[0] == "creature"
    assert role("Artifact", "", 4)[0] == "creature"                                    # Diabolic Machine
    assert role("Artifact", "|1: gain life", 0)[0] == "other"
    assert role("Instant", "lightning bolt deals 3 damage to target creature or player.") == ("burn", 3)
    assert role("Instant", "bury target non-black, non-artifact creature.") == ("burn", 99)
    assert role("Instant", "fireball deals x damage divided among any number of targets")[0] == "other"
    assert role("Enchant", "target creature gets +2/+2.")[0] == "buff"
    assert role("Enchant", "target creature gains flying.")[0] == "buff"
    assert role("Enchant", "wanderlust deals 1 damage to target creature's controller during that player's upkeep.")[0] == "curse"
    assert role("Enchant", "target land is destroyed")[0] == "other"                    # an aura for a land is not played


def test_targets_are_my_best_creature_for_a_buff_and_their_best_killable_one_for_burn(ap):
    def cr(name, p, t, cmc, player):
        return dict(name=name, player=player, parent="Player Territory" if player == 0 else "Oppon Territory",
                    fact=dict(type="Summon", power=p, toughness=t, cmc=cmc, role="creature", flying=False))
    mine = [cr("Falcon", 1, 1, 2, 0), cr("Ogre", 2, 2, 3, 0)]
    theirs = [cr("Giant", 3, 3, 3, 1), cr("Rats", 1, 1, 1, 1)]
    ap.mine = lambda cards: [c for c in cards if c["player"] == 0]
    ap.theirs = lambda cards: [c for c in cards if c["player"] == 1]
    cards = mine + theirs
    buff = dict(fact=dict(role="buff", damage=0, cmc=1))
    bolt = dict(fact=dict(role="burn", damage=3, cmc=1))
    weak = dict(fact=dict(role="burn", damage=1, cmc=1))
    assert ap.pick_target(buff, cards)["name"] == "Ogre"
    assert ap.pick_target(bolt, cards)["name"] == "Giant"                              # the one it can kill that costs the most
    assert ap.pick_target(weak, cards)["name"] == "Rats"
    assert ap.pick_target(bolt, mine) is None                                          # nothing of theirs to hit


def test_mana_creatures_pay_for_spells_after_the_lands(ap):
    def src(name, tapped=False):
        return dict(name=name, tapped=tapped, slot=0)
    elves, forest, mountain = src("Llanowar Elves"), src("Forest"), src("Mountain")
    plan = ap.pay_plan(card("Gypsies", cost="010002"), [elves, forest, mountain])        # G + 2 generic
    assert plan[0] is forest or plan[0] is elves                                          # the G comes from a green source
    assert len(plan) == 3
    plan = ap.pay_plan(card("Ogre", cost="000003"), [elves, forest, mountain])           # generic only: lands first, the Elves stay home
    assert elves not in plan[:2]
    assert ap.pay_plan(card("Fire", cost="000200"), [elves, forest, mountain]) is None  # RR: the Elves make green


def test_best_set_spends_the_most_mana_and_prefers_creatures(ap):
    f = lambda name, cost, role="creature": dict(name=name, fact=dict(card(name, cost=cost), role=role))     # noqa: E731
    lands = [dict(name="Mountain", tapped=False, slot=i) for i in range(4)]
    one, two, four = f("One", "000001"), f("Two", "000002"), f("Four", "000004")
    chosen = ap.best_set([(one, None), (two, None), (four, None)], lands)
    assert sorted(c["name"] for c, _ in chosen) == ["Four"]                               # 4 mana of 4, rather than 3 for One + Two
    chosen = ap.best_set([(one, None), (two, None)], lands[:3])
    assert sorted(c["name"] for c, _ in chosen) == ["One", "Two"]
    assert ap.best_set([(four, None)], lands[:3]) == []
