/*
 * ai_plan.c - the AI's recorded plan: Ai_RecordChoice, Ai_ReplayChoice, Ai_CommitBestPlan, Ai_ClearPlan,
 * Ai_GetPlanCursor, Ai_PlanCursorBack, Ai_PeekPlannedSlot, Ai_PeekPlannedChoice and Ai_GetLandColorMasks.
 *
 * MAGIC.EXE 0x004ab28b / 0x004ab3f3 / 0x004ab45f / 0x004ab1ef / 0x004ab510 / 0x004ab525 / 0x004ab35e / 0x004ab3a9 /
 * 0x004acb7f, DUEL.EXE 0x0043064a / 0x004307b2 / 0x0043081e / 0x004305ae / 0x004308cf / 0x004308e4 / 0x0043071d /
 * 0x00430768 / 0x00431f41. The AI plays by random rollouts (docs/SYMBOL_VERIFICATION.md, "The AI"): every choice a
 * rollout makes is appended to a trial list (Ai_RecordChoice); a rollout that beats the best score is copied to the
 * best list (Ai_CommitBestPlan); when the search ends the game replays the best list (Ai_ReplayChoice). The lists are
 * 256-entry arrays of dwords (choice, packed slot, card index, mode), indexed by one shared cursor. A choice of 99
 * means "no recorded choice". Not here: Ai_BeginTrial, which calls the 0xb640-byte game-state restore.
 *
 * Written from the decompiled bodies. Ai_ReplayChoice also executes `if (best_mode[cursor] != mode) mode |= 0x100`
 * just before it clears `mode`; the decompiler drops that dead store and so does this code (the final memory is the
 * same). Compares of the cursor are signed (jge/jle in the binary).
 */
#include "engine.h"

#define AI_LIST_MAX 0x100
#define AI_NO_CHOICE 99u

static uint32_t entry(uint32_t base, int32_t i)
{
    return base + (uint32_t)i * 4u;
}

void Native_Ai_RecordChoice(Vm *vm)
{
    NATIVE_ENTER(FN_AI_RECORD_CHOICE);
    Mem *m = vm->mem;
    const Layout *L = vm->L;
    int32_t n = (int32_t)mem_rd32(m, L->ai_cursor);

    if (n < AI_LIST_MAX) {
        uint32_t packed = mem_rd32(m, L->ai_packed_slot);
        /* The card index of the slot the packed value names: low byte slot, bit 8 player (0xff reads past the table
         * when the packed value is -1, exactly as the original does). */
        uint32_t slot_card = slot_addr(vm, (int32_t)((packed & 0x100u) >> 8), (int32_t)(packed & 0xffu), SLOT_CARD);

        mem_wr32(m, entry(L->ai_trial_slot, n), packed);
        mem_wr32(m, entry(L->ai_trial_card, n), mem_rd32(m, slot_card));
        mem_wr32(m, entry(L->ai_trial_mode, n), mem_rd32(m, L->ai_plan_mode));
        mem_wr32(m, entry(L->ai_trial_choice, n), mem_rd32(m, L->ai_choice_value));
        mem_wr32(m, L->ai_cursor, (uint32_t)(n + 1));
        if (mem_rd32(m, L->ai_trial_choice) == AI_NO_CHOICE || mem_rd32(m, L->ai_best_choice) == AI_NO_CHOICE)
            mem_wr32(m, L->ai_packed_slot, 0xffffffffu);
    } else {
        mem_wr32(m, L->ai_overflow_flag, 1);
    }
    mem_wr32(m, L->ai_plan_mode, 0);
}

void Native_Ai_ReplayChoice(Vm *vm)
{
    NATIVE_ENTER(FN_AI_REPLAY_CHOICE);
    Mem *m = vm->mem;
    const Layout *L = vm->L;
    int32_t n = (int32_t)mem_rd32(m, L->ai_cursor);
    uint32_t choice;

    mem_wr32(m, L->ai_packed_slot, mem_rd32(m, entry(L->ai_best_slot, n)));
    choice = mem_rd32(m, entry(L->ai_best_choice, n));
    mem_wr32(m, L->ai_choice_value, choice);
    if (choice != AI_NO_CHOICE)
        mem_wr32(m, L->ai_cursor, (uint32_t)(n + 1));
    mem_wr32(m, L->ai_plan_mode, 0);
}

void Native_Ai_CommitBestPlan(Vm *vm)
{
    NATIVE_ENTER(FN_AI_COMMIT_BEST_PLAN);
    Mem *m = vm->mem;
    const Layout *L = vm->L;
    int32_t n = (int32_t)mem_rd32(m, L->ai_cursor);
    int32_t i;

    for (i = 0; i < n; i++) {
        mem_wr32(m, entry(L->ai_best_choice, i), mem_rd32(m, entry(L->ai_trial_choice, i)));
        mem_wr32(m, entry(L->ai_best_slot, i), mem_rd32(m, entry(L->ai_trial_slot, i)));
        mem_wr32(m, entry(L->ai_best_card, i), mem_rd32(m, entry(L->ai_trial_card, i)));
        mem_wr32(m, entry(L->ai_best_mode, i), mem_rd32(m, entry(L->ai_trial_mode, i)));
    }
    mem_wr32(m, entry(L->ai_best_choice, n), AI_NO_CHOICE);
    if (mem_rd32(m, L->ai_best_choice) == AI_NO_CHOICE)
        mem_wr32(m, L->ai_best_len, (uint32_t)n);
    mem_wr32(m, L->ai_committed, 1);
}

void Native_Ai_ClearPlan(Vm *vm)
{
    NATIVE_ENTER(FN_AI_CLEAR_PLAN);
    mem_wr32(vm->mem, vm->L->ai_cursor, 0);
    mem_wr32(vm->mem, vm->L->ai_best_choice, AI_NO_CHOICE);
}

uint32_t Native_Ai_GetPlanCursor(Vm *vm)
{
    NATIVE_ENTER(FN_AI_GET_PLAN_CURSOR);
    return mem_rd32(vm->mem, vm->L->ai_cursor);
}

void Native_Ai_PlanCursorBack(Vm *vm)
{
    NATIVE_ENTER(FN_AI_PLAN_CURSOR_BACK);
    int32_t n = (int32_t)mem_rd32(vm->mem, vm->L->ai_cursor);

    mem_wr32(vm->mem, vm->L->ai_cursor, n < 1 ? 0u : (uint32_t)(n - 1));
}

/* Outside the AI's thinking: load the planned packed slot `offset` entries past the cursor and keep only its low 12
 * bits (the slot and player, without the mode bits). Returns 0. */
uint32_t Native_Ai_PeekPlannedSlot(Vm *vm, int32_t offset)
{
    NATIVE_ENTER(FN_AI_PEEK_PLANNED_SLOT);
    Mem *m = vm->mem;
    const Layout *L = vm->L;

    if ((int32_t)mem_rd32(m, L->is_ai_thinking) != 1) {
        int32_t n = (int32_t)mem_rd32(m, L->ai_cursor);
        uint32_t packed = mem_rd32(m, entry(L->ai_best_slot, offset + n));

        mem_wr32(m, L->ai_packed_slot, packed);
        if (packed != 0xffffffffu)
            mem_wr32(m, L->ai_packed_slot, packed & 0xfffu);
    }
    return 0;
}

/* Outside the AI's thinking: load the planned choice `offset` entries past the cursor, with "none" (99) read as 0. */
uint32_t Native_Ai_PeekPlannedChoice(Vm *vm, int32_t offset)
{
    NATIVE_ENTER(FN_AI_PEEK_PLANNED_CHOICE);
    Mem *m = vm->mem;
    const Layout *L = vm->L;

    if ((int32_t)mem_rd32(m, L->is_ai_thinking) != 1) {
        int32_t n = (int32_t)mem_rd32(m, L->ai_cursor);
        uint32_t choice = mem_rd32(m, entry(L->ai_best_choice, offset + n));

        mem_wr32(m, L->ai_peeked_choice, choice);
        if (choice == AI_NO_CHOICE)
            mem_wr32(m, L->ai_peeked_choice, 0);
    }
    return 0;
}

/* Two bitmasks of the colours (bit i - 1 for colour i, 1 to 5) in which a player has a land count above zero, written
 * through the two out-pointers (guest addresses; either may be null). */
void Native_Ai_GetLandColorMasks(Vm *vm, uint32_t out_x, uint32_t out_y)
{
    NATIVE_ENTER(FN_AI_GET_LAND_COLOR_MASKS);
    Mem *m = vm->mem;
    const Layout *L = vm->L;
    uint32_t mask_x = 0, mask_y = 0;
    int32_t colour;

    for (colour = 1; colour < 6; colour++) {
        if (0 < (int32_t)mem_rd32(m, entry(L->land_counts_x, colour)))
            mask_x |= 1u << (((uint32_t)colour - 1u) & 0x1fu);
        if (0 < (int32_t)mem_rd32(m, entry(L->land_counts_y, colour)))
            mask_y |= 1u << (((uint32_t)colour - 1u) & 0x1fu);
    }
    if (out_x != 0)
        mem_wr32(m, out_x, mask_x);
    if (out_y != 0)
        mem_wr32(m, out_y, mask_y);
}
