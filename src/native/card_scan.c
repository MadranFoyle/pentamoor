/*
 * card_scan.c - Magic_ScanCards: run every in-play card's own handler for one event.
 *
 * MAGIC.EXE 0x00473f06, DUEL.EXE 0x0048c5a8. The duel engine's central dispatcher: card behaviour lives in per-card
 * handler functions (one pointer per master record, +0x10), and almost every rules question is answered by scanning the
 * cards and letting each one react to an event code (docs/SYMBOL_VERIFICATION.md). Written from the decompiled body
 * (identical in both programs apart from addresses) and checked against the disassembly: every compare is signed.
 *
 * The handlers are the hundreds of per-card scripts and are not native: each is reached through vm_call_at with the
 * address read from memory. Paths the original ends in an assert or a fatal error (a scan nested ten deep, a card index
 * out of range) are not implemented here and stop the run.
 */
#include "engine.h"

#define SCAN_ORDER_MAX 500 /* 0x1f4 */
#define SLOTS_PER_PLAYER 0x50

static uint32_t order_entry(uint32_t base, int32_t i)
{
    return base + (uint32_t)i * 4u;
}

static void run_handler(Vm *vm, int32_t card, int32_t player, int32_t slot, int32_t event_code)
{
    uint32_t args[3];

    args[0] = (uint32_t)player;
    args[1] = (uint32_t)slot;
    args[2] = (uint32_t)event_code;
    vm_call_at(vm, CALLEE_CARD_HANDLER, mem_rd32(vm->mem, master_addr(vm, card, MASTER_HANDLER)), 3, args);
}

void Native_Magic_ScanCards(Vm *vm, int32_t event_code)
{
    NATIVE_ENTER(FN_SCAN_CARDS);
    Mem *m = vm->mem;
    const Layout *L = vm->L;
    uint32_t saved = mem_rd32(m, L->query_saved);
    int32_t depth, player, slot, i;
    uint32_t args[3];

    mem_wr32(m, L->scan_event_code, (uint32_t)event_code);
    mem_wr32(m, L->scan_counter, mem_rd32(m, L->scan_counter) + 1);
    depth = (int32_t)mem_rd32(m, L->scan_depth) + 1;
    mem_wr32(m, L->scan_depth, (uint32_t)depth);
    if (9 < depth)
        NATIVE_UNIMPLEMENTED("Magic_ScanCards: scans nested ten deep (the original asserts nScan<10)");

    /* The highest used slot of each player, recomputed from the slot table. */
    for (player = 0; player < 2; player++)
        for (slot = 0; slot < SLOTS_PER_PLAYER; slot++)
            if ((int32_t)mem_rd32(m, slot_addr(vm, player, slot, SLOT_CARD)) != -1)
                mem_wr32(m, L->player_card_count + (uint32_t)player * 4u, (uint32_t)(slot + 1));

    /* `player` leaks out of the loop: the original reuses one variable, so the turn-player test after the loop compares
     * against the last list entry examined, or against 2 (the first loop's end value) when the list is empty. */
    for (i = 0; i < SCAN_ORDER_MAX; i++) {
        int32_t card;

        if ((int32_t)mem_rd32(m, order_entry(L->scan_order_player, i)) == -1)
            break;
        player = (int32_t)mem_rd32(m, order_entry(L->scan_order_player, i));
        slot = (int32_t)mem_rd32(m, order_entry(L->scan_order_slot, i));
        if ((int32_t)mem_rd32(m, slot_addr(vm, player, slot, SLOT_DISPLAY)) != i)
            continue;
        card = (int32_t)mem_rd32(m, slot_addr(vm, player, slot, SLOT_CARD));
        if (card == -1)
            continue;
        if ((mem_rd8(m, slot_addr(vm, player, slot, SLOT_FLAGS)) & 2) == 0 &&
            (mem_rd8(m, slot_addr(vm, player, slot, SLOT_FLAGS)) & 0x20) == 0)
            continue;

        mem_wr32(m, L->scan_current_card, (uint32_t)(player * 0x80 + slot));
        if (card < 0 || (int32_t)mem_rd32(m, L->master_count) + 0x10 < card)
            NATIVE_UNIMPLEMENTED("Magic_ScanCards: card index out of range (the original reports a fatal error)");
        run_handler(vm, card, player, slot, event_code);

        /* At the start of a turn: a card that is in play and untapped-looking (flags & 0x14 == 4) may get marked. */
        if (event_code == 0x15 && (int32_t)mem_rd32(m, L->turn_player) == player &&
            (mem_rd8(m, slot_addr(vm, player, slot, SLOT_FLAGS)) & 0x14) == 4) {
            args[0] = (uint32_t)player;
            args[1] = (uint32_t)slot;
            if (vm_call(vm, CALLEE_SCAN_CHECK, 2, args) == 0) {
                mem_wr32(m, slot_addr(vm, player, slot, SLOT_FLAGS),
                         mem_rd32(m, slot_addr(vm, player, slot, SLOT_FLAGS)) | 0x10u);
                mem_wr32(m, L->scan_flag, 0xffffffffu);
                args[2] = 0x81;
                vm_call(vm, CALLEE_BROADCAST_CARD_EVENT, 3, args);
            }
        }
    }
    /* `player` is the leaked variable described above (2 if the loop never assigned it). */
    if (event_code == 0x15 && (int32_t)mem_rd32(m, L->turn_player) == player)
        vm_call(vm, CALLEE_COMBAT_DAMAGE_STEP, 0, args);

    mem_wr32(m, L->scan_depth, mem_rd32(m, L->scan_depth) - 1u);
    if ((int32_t)mem_rd32(m, L->global_handler) != -1) {
        args[0] = 0;
        args[1] = 0x4e;
        args[2] = (uint32_t)event_code;
        vm_call_at(vm, CALLEE_CARD_HANDLER,
                   mem_rd32(m, master_addr(vm, (int32_t)mem_rd32(m, L->global_handler), MASTER_HANDLER)), 3, args);
    }
    mem_wr32(m, L->query_saved, saved);
}
