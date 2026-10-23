/*
 * ai_eval.c - how the AI scores a board: Ai_EvaluateBoard and Ai_PenalizeCounterattack.
 *
 * The AI plays by random rollouts (docs/SYMBOL_VERIFICATION.md, "The AI"): it plays out a trial, then scores the resulting board
 * with Ai_EvaluateBoard(player), a signed zero-sum number (about 3,000 calls in a two-second search). The score is a sum over both
 * players of what each is worth: life (a falling amount per point, weighted per player), the lands each player has in each
 * colour, the cards in each player's hand, and for each permanent a value that depends on what it is: a creature on its power,
 * toughness and abilities (and, on the AI's turn, whether the opponent can block or kill it), a land on whether it is untapped,
 * a spell in hand on its cost class. When it is the evaluated player's own turn, Ai_PenalizeCounterattack then lowers the
 * score by what the opponent's best attackers could do back.
 *
 * Reimplements the functions of DUEL.EXE named above, from its machine code (casts and divisions are easy to get wrong in a plain C reading; every divide here is the compiler's
 * truncating one, every compare signed), and checked three ways: against vectors recorded from the original and from fuzzed
 * boards, against its own machine code translated by tools/lift on every call of a real game (the host's shadow mode), and by
 * a whole-game comparison with the original. The two programs carry the same code at different addresses (the two
 * programs' functions were lined up by their code).
 *
 * Not implemented, where the original reads or writes outside its own locals or is a debugging aid: the on-screen score
 * breakdown (0x005ef574 set), more than 16 of one player's creatures in the counterattack's arrays, and an aura whose
 * target index falls outside the 2 x 80 table of attachments.
 */
#include <string.h>

#include "engine.h"

/* the slot flags (low byte) as they are now */
#define FLAGS() flags8(vm, p, s)

typedef struct {
    uint32_t debug_mode;   /* 0x005ef574 / 0x0067b9a4: the developer's score display, normally 0 */
    uint32_t target_a;     /* 0x00676504 / 0x006a492c: a player the evaluation weighs differently (0x48 per pile card, else 0x18) */
    uint32_t life;         /* int[2]: life totals */
    uint32_t weight_a;     /* 0x00666710 / 0x00695e80: int[2], per player, scales life and attackers */
    uint32_t weight_b;     /* 0x00666718 / 0x00695e88: int[2], per player, scales what a permanent is worth */
    uint32_t lands;        /* 0x0068ef50 / 0x0063ee30: per player 0x20 apart, a count per colour (4 bytes each, colour 1 to 5) */
    uint32_t piles;        /* 0x0068f2fc / 0x0063eeac: per player 0x20 apart, a count the first term of a player's part uses */
    uint32_t part_scores;  /* 0x0068ecb8 / 0x006b2538: int[2], each player's part of the last score, kept */
    uint32_t reading;      /* 0x006c121c / 0x00676c8c: when not 0 the turn-based refinements are skipped */
    uint32_t land_handler; /* 0x00464774 / 0x004e2fe8: the handler of the card that is worth 1 when it is not in play */
    uint32_t target_b;     /* 0x00676510 / 0x006a49e0: the player whose creatures the counterattack boosts by their handlers */
    uint32_t saved_lands;  /* 0x0068ed10 / 0x0063edd0: per player 0x20 apart, 8 words, borrowed by the counterattack */
} EvalAddrs;

static const EvalAddrs EVAL_DUEL = {0x005ef574, 0x00676504, 0x00681ea8, 0x00666710, 0x00666718, 0x0068ef50,
                                    0x0068f2fc, 0x0068ecb8, 0x006c121c, 0x00464774, 0x00676510, 0x0068ed10};
static const EvalAddrs EVAL_MAGIC = {0x0067b9a4, 0x006a492c, 0x006a4a00, 0x00695e80, 0x00695e88, 0x0063ee30,
                                     0x0063eeac, 0x006b2538, 0x00676c8c, 0x004e2fe8, 0x006a49e0, 0x0063edd0};

static const EvalAddrs *addrs(const Layout *L)
{
    return L->program[0] == 'D' ? &EVAL_DUEL : &EVAL_MAGIC;
}

#define SLOT_B39 0x39u /* byte: ability bits of the second byte of the abilities word (bit 3 tested by the counterattack) */
#define SLOT_VALUE_40 0x40u /* dword: what the counterattack minimises when it picks a blocker */
#define MASTER_BYTE_5 0x05u /* byte: non-zero when the creature's power counts (read as signed) */
#define MASTER_BYTE_8 0x08u /* byte: per-card number an artifact-like permanent (type 0x40) is worth (read as signed) */

/* Signed truncating division, as the compiler's cdq/idiv or shift-and-correct sequences do, and a 32-bit wrapping product. */
static int32_t div_trunc(int32_t a, int32_t b)
{
    return a / b;
}

static int32_t mul(int32_t a, int32_t b)
{
    return (int32_t)((uint32_t)a * (uint32_t)b);
}

static uint32_t rd(Vm *vm, uint32_t a)
{
    return mem_rd32(vm->mem, a);
}

static int32_t card_of(Vm *vm, int32_t p, int32_t s)
{
    return (int32_t)rd(vm, slot_addr(vm, p, s, SLOT_CARD));
}

/* The original tests the flags with byte instructions almost everywhere, and reading more than it did is a read of memory a vector
 * does not have: flags8 is the low byte, flags_of the whole dword (where the original reads the dword). */
static uint32_t flags8(Vm *vm, int32_t p, int32_t s)
{
    return mem_rd8(vm->mem, slot_addr(vm, p, s, SLOT_FLAGS));
}

static uint32_t flags_of(Vm *vm, int32_t p, int32_t s)
{
    return rd(vm, slot_addr(vm, p, s, SLOT_FLAGS));
}

static int32_t count_of(Vm *vm, int32_t p)
{
    return (int32_t)rd(vm, vm->L->player_card_count + 4u * (uint32_t)p);
}

static uint32_t master_byte(Vm *vm, int32_t card, uint32_t field)
{
    return mem_rd8(vm->mem, master_addr(vm, card, field));
}

/* the low byte of the master record's flags dword (the original tests a byte) */
static uint32_t master_flags8(Vm *vm, int32_t card)
{
    return master_byte(vm, card, MASTER_FLAGS);
}

/* A native function called from here runs as native code when the host replaces it, else the original is called. */
static uint32_t query(Vm *vm, int32_t p, int32_t s, int32_t code, int32_t target)
{
    if (native_disabled[FN_QUERY_CARD_ATTRIBUTE]) {
        uint32_t a[4] = {(uint32_t)p, (uint32_t)s, (uint32_t)code, (uint32_t)target};
        return vm_call_at(vm, CALLEE_FUNCTION, vm->L->entry[FN_QUERY_CARD_ATTRIBUTE], 4, a);
    }
    return Native_Magic_QueryCardAttribute(vm, p, s, code, (uint32_t)target);
}

/* The two colour masks Ai_GetLandColorMasks returns: x for the counts at land_counts_x, y for land_counts_y. */
static void land_masks(Vm *vm, uint32_t *mask_x, uint32_t *mask_y)
{
    const Layout *L = vm->L;
    int32_t colour;
    *mask_x = *mask_y = 0;
    for (colour = 1; colour < 6; colour++) {
        if (0 < (int32_t)rd(vm, L->land_counts_x + 4u * (uint32_t)colour))
            *mask_x |= 1u << (colour - 1);
        if (0 < (int32_t)rd(vm, L->land_counts_y + 4u * (uint32_t)colour))
            *mask_y |= 1u << (colour - 1);
    }
}

/* 0x0048b2c9 / 0x00472c0c: whether creature `slot` of player `p` could be blocked, from the opposing creature (q, j) side;
 * not native. */
static int32_t blockable(Vm *vm, int32_t q, int32_t j, int32_t p, int32_t slot, uint32_t abilities, uint32_t mask)
{
    uint32_t a[6] = {(uint32_t)q, (uint32_t)j, (uint32_t)p, (uint32_t)slot, abilities, mask};
    return (int32_t)vm_call_at(vm, CALLEE_FUNCTION, vm->L->callee[CALLEE_AI_ATTACK_CHECK], 6, a);
}

int32_t Native_Ai_EvaluateBoard(Vm *vm, int32_t player)
{
    NATIVE_ENTER(FN_AI_EVALUATE_BOARD);
    const Layout *L = vm->L;
    const EvalAddrs *E = addrs(L);
    Mem *m = vm->mem;
    int8_t attached[160]; /* [owner-colour * 0x50 + target slot]: a bit per player whose aura is on that permanent */
    uint32_t masks[2];
    int32_t score, part, other, p, life_sum, k, s, card, value, i;

    if (rd(vm, E->debug_mode) != 0)
        NATIVE_UNIMPLEMENTED("Ai_EvaluateBoard with the developer's score display on");
    mem_wr32(m, L->query_saved, 1);
    other = 1 - player;
    land_masks(vm, &masks[0], &masks[1]);
    memset(attached, 0, sizeof(attached));

    /* life: a falling sum 24/1 + 12, 24/2 + 12, ... for each point, scaled by the player's weight and the eighth taken */
    life_sum = 0;
    for (k = 1; k <= (int32_t)rd(vm, E->life + 4u * (uint32_t)player); k++)
        life_sum += div_trunc(0x18, k) + 0xc;
    score = div_trunc(mul((int32_t)rd(vm, E->weight_a + 4u * (uint32_t)player), life_sum), 8);
    life_sum = 0;
    for (k = 1; k <= (int32_t)rd(vm, E->life + 4u * (uint32_t)other); k++)
        life_sum += div_trunc(0x18, k) + 0xc;
    score -= div_trunc(mul((int32_t)rd(vm, E->weight_a + 4u * (uint32_t)other), life_sum), 8);
    if ((int32_t)rd(vm, E->life + 4u * (uint32_t)player) < 1)
        score += mul((int32_t)rd(vm, E->life + 4u * (uint32_t)player) * 4 - 8, 75);
    if ((int32_t)rd(vm, E->life + 4u * (uint32_t)other) < 1)
        score -= mul((int32_t)rd(vm, E->life + 4u * (uint32_t)other) - 2, 256);

    for (p = 0; p < 2; p++) {
        int32_t opp = 1 - p;

        /* what the player's own piles and lands are worth */
        part = -mul(((int32_t)rd(vm, E->target_a) == p ? 0x30 : 0) + 0x18, (int32_t)rd(vm, E->piles + 0x20u * (uint32_t)p));
        for (k = 1; k < 6; k++)
            for (i = 1; i <= (int32_t)rd(vm, E->lands + 0x20u * (uint32_t)p + 4u * (uint32_t)k); i++)
                part += div_trunc(0x30, i);

        for (s = 0; s < count_of(vm, p); s++) {
            uint32_t type;

            card = card_of(vm, p, s);
            if (card == -1)
                continue;
            type = master_byte(vm, card, MASTER_TYPE);
            if (type & 0x80)
                continue;
            value = 1; /* the original reads the flags again at every test: a query's handlers can change them */

            if (type & 2) { /* a creature */
                uint32_t abilities = query(vm, p, s, 0x34, -1);
                int32_t power2 = (int32_t)((query(vm, p, s, 0x32, -1) & 0xffffbfffu) * 2u), toughness;

                if ((int8_t)master_byte(vm, card, MASTER_BYTE_5) == 0)
                    power2 = 0;
                toughness = (int32_t)(query(vm, p, s, 0x33, -1) & 0xffffbfffu);
                value = div_trunc(mul(power2 + 3, toughness + 4), 2);
                if ((FLAGS() & 0x10) && (int32_t)rd(vm, L->turn_player) == p)
                    value -= 1;
                if (abilities & 0x80)
                    value = div_trunc(mul(value, 3), 2);
                if (abilities & 0x100)
                    value = div_trunc(mul(value, 3), 2);
                if (master_flags8(vm, card) & 3)
                    value = div_trunc(mul(value, 3), 2);
                if (abilities & 0x40)
                    value = div_trunc(mul(toughness + 1, value), 2);
                if (abilities & 0x200)
                    value = div_trunc(mul(value, 3), 2);

                /* on the evaluated player's turn, can the opponent's creature be blocked, and does it die doing it? */
                if (rd(vm, E->reading) == 0 && p != player && (int32_t)rd(vm, L->turn_player) == player && (FLAGS() & 2)) {
                    int32_t seen = 0, j;

                    abilities = query(vm, p, s, 0x34, -1);
                    for (j = 0; j < count_of(vm, opp); j++) {
                        if (!blockable(vm, opp, j, p, s, abilities, masks[p]))
                            continue;
                        seen |= 1;
                        if ((int32_t)query(vm, opp, j, 0x33, s) > power2 || (int32_t)query(vm, opp, j, 0x32, s) >= toughness) {
                            seen |= 2;
                            break;
                        }
                    }
                    if (!(seen & 2)) {
                        part += div_trunc(mul(mul((int32_t)rd(vm, E->weight_a + 4u * (uint32_t)opp), power2), 24), 16);
                        if (seen == 0 && (int32_t)rd(vm, E->life + 4u * (uint32_t)opp) <= power2)
                            part += 0x100;
                    }
                }
                if (FLAGS() & 2)
                    value = mul(value, 3);
                else if (rd(vm, master_addr(vm, card, MASTER_HANDLER)) == E->land_handler)
                    value = 1;
                value = div_trunc(mul((int32_t)rd(vm, E->weight_b + 4u * (uint32_t)p), value), 8);
            }
            if (type & 1) { /* a land: worth 2 in hand, and in play 1 untapped (0 tapped) */
                if (!(FLAGS() & 2))
                    value = 2;
                else
                    value = (FLAGS() & 0x10) ? 0 : 1;
            }
            if (type == 0x40 && (FLAGS() & 2))
                value = div_trunc(((int8_t)master_byte(vm, card, MASTER_BYTE_8) * 3 + 3) * 4, 2);
            if (type == 4 && (FLAGS() & 2) && (int8_t)mem_rd8(m, slot_addr(vm, p, s, SLOT_CHAR_12)) != -1 &&
                (int32_t)rd(vm, slot_addr(vm, p, s, SLOT_DWORD_28)) != -1) {
                /* an aura: remember on which permanent it is, by player */
                int32_t at = (int8_t)mem_rd8(m, slot_addr(vm, p, s, SLOT_CHAR_12)) * 0x50 + (int32_t)rd(vm, slot_addr(vm, p, s, SLOT_DWORD_28));

                if (at < 0 || at >= (int32_t)sizeof(attached))
                    NATIVE_UNIMPLEMENTED("Ai_EvaluateBoard: an aura whose target is outside its table (the original writes over its locals)");
                attached[at] = (int8_t)(attached[at] | (1 << p));
            }
            if ((type & 0x38) && !(FLAGS() & 2)) { /* a spell in hand: its cost class */
                uint32_t a[1] = {(uint32_t)card};
                value = mul((int32_t)vm_call_at(vm, CALLEE_FUNCTION, L->callee[CALLEE_AI_CARD_COST_CLASS], 1, a), 12);
            }
            if ((type & 4) && !(FLAGS() & 2))
                value = 3;
            part += value;
        }
        mem_wr32(m, E->part_scores + 4u * (uint32_t)p, (uint32_t)part);
        if (p == player)
            score += part;
        else
            score -= part;
    }

    /* an aura helps its owner's permanent and hurts the other's */
    for (p = 0; p < 2; p++)
        for (s = 0; s < count_of(vm, p); s++) {
            if ((1 << player) & attached[p * 0x50 + s])
                score += 2;
            if ((1 << (1 - player)) & attached[p * 0x50 + s])
                score -= 2;
        }
    if (rd(vm, E->reading) == 0 && (int32_t)rd(vm, L->turn_player) == player)
        score = Native_Ai_PenalizeCounterattack(vm, player, score);
    mem_wr32(m, L->query_saved, 0);
    return score;
}

/* The opponent's best attackers' damage to the evaluated player, which the evaluation above lowers the score by: for each of up
 * to eight of the opponent's untapped creatures with the highest power (tried in that order), whether the player has a creature
 * that can block it without dying, and if not the damage it does (or what the cheapest blocker's loss costs, whichever the AI
 * would rather give up). The opponent's land counts are borrowed for the duration (8 words, kept as bytes: the original puts them
 * back sign-extended from a byte, which is what this does). */
int32_t Native_Ai_PenalizeCounterattack(Vm *vm, int32_t player, int32_t score)
{
    NATIVE_ENTER(FN_AI_PENALIZE_COUNTERATTACK);
    const Layout *L = vm->L;
    const EvalAddrs *E = addrs(L);
    int32_t other = 1 - player, k, s, n = 0, damage = 0;
    int8_t saved[8], index_of[0x50];
    int32_t power[16], toughness[16], value40[16];
    int32_t top[8][3]; /* the opponent's attackers: slot, power, toughness */
    uint32_t mask_x, mask_y;

    land_masks(vm, &mask_x, &mask_y);
    for (k = 0; k < 8; k++) {
        uint32_t at = E->saved_lands + 0x20u * (uint32_t)other + 4u * (uint32_t)k;

        saved[k] = (int8_t)mem_rd8(vm->mem, at);
        mem_wr32(vm->mem, at, rd(vm, E->lands + 0x20u * (uint32_t)other + 4u * (uint32_t)k));
    }
    for (k = 0; k < 8; k++)
        top[k][1] = -1;
    memset(index_of, -1, sizeof(index_of)); /* the original leaves these unset: an entry is only read for a creature the first pass saw */

    /* the player's own creatures */
    for (s = 0; s < count_of(vm, player); s++) {
        int32_t card = card_of(vm, player, s);

        if (card == -1 || !(flags_of(vm, player, s) & 0x402) || !(master_byte(vm, card, MASTER_TYPE) & 2))
            continue;
        if (n >= 16 || s >= 0x50)
            NATIVE_UNIMPLEMENTED("Ai_PenalizeCounterattack: more creatures than the original's arrays hold");
        index_of[s] = (int8_t)n;
        power[n] = (int32_t)query(vm, player, s, 0x32, -1);
        toughness[n] = (int32_t)query(vm, player, s, 0x33, -1);
        value40[n] = (int32_t)rd(vm, slot_addr(vm, player, s, SLOT_VALUE_40));
        n++;
    }

    /* the opponent's attackers, the eight of highest power kept in order */
    for (s = 0; s < count_of(vm, other); s++) {
        int32_t card = card_of(vm, other, s), pw, tg;

        if (card == -1 || !(master_byte(vm, card, MASTER_TYPE) & 2) || !(flags8(vm, other, s) & 2))
            continue;
        if (!(master_byte(vm, card, 5) != 0 || (mem_rd8(vm->mem, slot_addr(vm, other, s, SLOT_B39)) & 8)))
            continue;
        pw = (int32_t)query(vm, other, s, 0x32, -1);
        tg = (int32_t)query(vm, other, s, 0x33, -1);
        if ((int32_t)rd(vm, E->target_b) == other) {
            uint32_t a[3] = {(uint32_t)other, (uint32_t)s, 0x39};

            if (master_flags8(vm, card) & 8)
                pw += (int32_t)vm_call_at(vm, CALLEE_CARD_HANDLER, rd(vm, master_addr(vm, card, MASTER_HANDLER)), 3, a);
            if (master_flags8(vm, card) & 0x10) {
                a[2] = 0x3a;
                tg += (int32_t)vm_call_at(vm, CALLEE_CARD_HANDLER, rd(vm, master_addr(vm, card, MASTER_HANDLER)), 3, a);
            }
        }
        for (k = 0; k < 8; k++) {
            int32_t j;

            if (pw <= top[k][1])
                continue;
            for (j = 7; k < j; j--) {
                top[j][0] = top[j - 1][0];
                top[j][1] = top[j - 1][1];
                top[j][2] = top[j - 1][2];
            }
            top[k][0] = s;
            top[k][1] = pw;
            top[k][2] = tg;
            break;
        }
    }

    for (k = 0; k < 8 && top[k][1] != -1; k++) {
        int32_t attacker = top[k][0], apw = top[k][1], atg = top[k][2], seen = 0, cheapest = 0, best = 0x7fff, mine;
        uint32_t abilities = query(vm, other, attacker, 0x34, -1);

        for (mine = 0; mine < count_of(vm, player); mine++) {
            int32_t card = card_of(vm, player, mine), who;
            uint32_t a2[2] = {(uint32_t)player, (uint32_t)mine}, mask;

            if (card == -1 || !(flags8(vm, player, mine) & 2) || !(master_byte(vm, card, MASTER_TYPE) & 2))
                continue;
            who = index_of[mine];
            if (who < 0)
                NATIVE_UNIMPLEMENTED("Ai_PenalizeCounterattack: a creature that became untapped-in-play since the first pass (the original reads stack garbage)");
            mask = vm_call_at(vm, CALLEE_FUNCTION, L->callee[CALLEE_SCAN_CHECK], 2, a2) == 0 ? 12u : 8u;
            if (flags_of(vm, player, mine) & mask)
                continue;
            if (!blockable(vm, player, mine, other, attacker, abilities, mask_x))
                continue;
            seen |= 1;
            if (apw < toughness[who] || atg <= power[who]) { /* it is stopped, or the blocker dies: the AI marks it and stops looking */
                seen |= 2;
                mem_wr32(vm->mem, slot_addr(vm, player, mine, SLOT_FLAGS), flags_of(vm, player, mine) | 8);
                break;
            }
            if (value40[who] < best) {
                best = value40[who];
                cheapest = mine;
            }
        }
        if (!(seen & 2)) {
            int32_t life = (int32_t)rd(vm, E->life + 4u * (uint32_t)player), divisor = life + 1, cost, price;

            if (divisor < 1)
                divisor = 1;
            if (divisor > 99)
                divisor = 99;
            cost = div_trunc(div_trunc(mul(mul((int32_t)rd(vm, E->weight_a + 4u * (uint32_t)player), apw), 24), 4), divisor);
            price = div_trunc(mul((int32_t)rd(vm, E->weight_b + 4u * (uint32_t)player), best), 16);
            if (seen == 0 || (price > cost && apw + damage < life)) {
                damage += apw;
                score -= cost;
            } else {
                score -= price;
                mem_wr32(vm->mem, slot_addr(vm, player, cheapest, SLOT_FLAGS), flags_of(vm, player, cheapest) | 8);
            }
        }
    }
    if ((int32_t)rd(vm, E->life + 4u * (uint32_t)player) <= damage && 0 < (int32_t)rd(vm, E->life + 4u * (uint32_t)other))
        score -= 0x100;
    for (k = 0; k < 8; k++)
        mem_wr32(vm->mem, E->saved_lands + 0x20u * (uint32_t)other + 4u * (uint32_t)k, (uint32_t)(int32_t)saved[k]);
    return score;
}
