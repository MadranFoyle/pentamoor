/*
 * engine.c - calls out of native code, and the table of native functions.
 */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "engine.h"

static const char *const CALLEE_NAMES[CALLEE_COUNT] = {
    [CALLEE_CARD_HANDLER] = "a card's event handler",
    [CALLEE_SCAN_CHECK] = "0x004728c3 (turn-start scan check)",
    [CALLEE_BROADCAST_CARD_EVENT] = "Magic_BroadcastCardEvent",
    [CALLEE_COMBAT_DAMAGE_STEP] = "0x00472fae (combat damage step)",
    [CALLEE_MARK_CARD] = "Pic_Subsystem_0044867e",
    [CALLEE_AFTER_MARK] = "Pic_Subsystem_004488a0",
    [CALLEE_FIND_FREE_SLOT] = "Pic_Subsystem_00451291 (find free slot)",
    [CALLEE_AI_ATTACK_CHECK] = "0x0048b2c9 (can the attacker be blocked)",
    [CALLEE_AI_CARD_COST_CLASS] = "0x004d7c20 (a card's cost class)",
    [CALLEE_AI_PREROLL_RANDOM] = "0x004398be (fill the table of random numbers)",
    [CALLEE_FUNCTION] = "a function called from lifted code",
};

const char *callee_name(Callee c)
{
    return (unsigned)c < CALLEE_COUNT ? CALLEE_NAMES[c] : "?";
}

uint32_t vm_call(Vm *vm, Callee callee, int nargs, const uint32_t *args)
{
    if (!vm->call) {
        fprintf(stderr, "native: call to %s with no call hook\n", callee_name(callee));
        abort();
    }
    return vm->call(vm->call_ctx, callee, vm->L->callee[callee], nargs, args);
}

uint64_t native_entries[FN_COUNT];
unsigned char native_disabled[FN_COUNT];
int native_exact_only;

int (*native_handler_dispatch)(Vm *vm, uint32_t addr, int nargs, const uint32_t *args, uint32_t *ret);

uint32_t vm_call_at(Vm *vm, Callee callee, uint32_t addr, int nargs, const uint32_t *args)
{
    uint32_t lifted_ret;
    if ((callee == CALLEE_CARD_HANDLER || callee == CALLEE_FUNCTION) && native_handler_dispatch &&
        native_handler_dispatch(vm, addr, nargs, args, &lifted_ret))
        return lifted_ret;
    if (!vm->call) {
        fprintf(stderr, "native: call to %s with no call hook\n", callee_name(callee));
        abort();
    }
    return vm->call(vm->call_ctx, callee, addr, nargs, args);
}

void native_unimplemented(const char *what, const char *file, int line)
{
    fprintf(stderr, "native: unimplemented: %s (%s:%d)\n", what, file, line);
    assert(0 && "unimplemented native code path");
    abort();
}

static uint32_t run_query(Vm *vm, const uint32_t *a)
{
    return Native_Magic_QueryCardAttribute(vm, (int32_t)a[0], (int32_t)a[1], (int32_t)a[2], a[3]);
}

static uint32_t run_is_mana_source(Vm *vm, const uint32_t *a)
{
    return Native_Magic_IsManaSource(vm, (int32_t)a[0], (int32_t)a[1]);
}

static uint32_t run_drop(Vm *vm, const uint32_t *a)
{
    (void)a;
    return Native_Magic_DropTopSpell(vm);
}

static uint32_t run_push(Vm *vm, const uint32_t *a)
{
    return Native_Magic_PushSpellStack(vm, (int32_t)a[0], (int32_t)a[1], (int32_t)a[2], (int32_t)a[3], a[4]);
}

static uint32_t run_clear(Vm *vm, const uint32_t *a)
{
    (void)a;
    return Native_Magic_ClearSpellStack(vm);
}

static uint32_t run_color_flags(Vm *vm, const uint32_t *a)
{
    return Native_Card_GetColorAndTypeFlags(vm, (int32_t)a[0], (int32_t)a[1]);
}

static uint32_t run_push_event_context(Vm *vm, const uint32_t *a)
{
    (void)a;
    Native_Magic_PushEventContext(vm);
    return 0;
}

static uint32_t run_pop_event_context(Vm *vm, const uint32_t *a)
{
    (void)a;
    Native_Magic_PopEventContext(vm);
    return 0;
}

static uint32_t run_is_tapped(Vm *vm, const uint32_t *a)
{
    return Native_Card_IsInPlay(vm, (int32_t)a[0], (int32_t)a[1]);
}

static uint32_t run_mask_to_index(Vm *vm, const uint32_t *a)
{
    (void)vm;
    return Native_Card_ColorMaskToColorIndex(a[0]);
}

static uint32_t run_remap_ff(Vm *vm, const uint32_t *a)
{
    return (uint32_t)Native_Card_RemapColorIndexFF(vm, (int32_t)a[0], (int32_t)a[1], (int32_t)a[2]);
}

static uint32_t run_remap_f9(Vm *vm, const uint32_t *a)
{
    return (uint32_t)Native_Card_RemapColorIndexF9(vm, (int32_t)a[0], (int32_t)a[1], (int32_t)a[2]);
}

static uint32_t run_ai_record(Vm *vm, const uint32_t *a)
{
    (void)a;
    Native_Ai_RecordChoice(vm);
    return 0;
}

static uint32_t run_ai_replay(Vm *vm, const uint32_t *a)
{
    (void)a;
    Native_Ai_ReplayChoice(vm);
    return 0;
}

static uint32_t run_ai_commit(Vm *vm, const uint32_t *a)
{
    (void)a;
    Native_Ai_CommitBestPlan(vm);
    return 0;
}

static uint32_t run_ai_clear(Vm *vm, const uint32_t *a)
{
    (void)a;
    Native_Ai_ClearPlan(vm);
    return 0;
}

static uint32_t run_ai_cursor(Vm *vm, const uint32_t *a)
{
    (void)a;
    return Native_Ai_GetPlanCursor(vm);
}

static uint32_t run_ai_cursor_back(Vm *vm, const uint32_t *a)
{
    (void)a;
    Native_Ai_PlanCursorBack(vm);
    return 0;
}

static uint32_t run_ai_peek_slot(Vm *vm, const uint32_t *a)
{
    return Native_Ai_PeekPlannedSlot(vm, (int32_t)a[0]);
}

static uint32_t run_ai_peek_choice(Vm *vm, const uint32_t *a)
{
    return Native_Ai_PeekPlannedChoice(vm, (int32_t)a[0]);
}

static uint32_t run_ai_land_masks(Vm *vm, const uint32_t *a)
{
    Native_Ai_GetLandColorMasks(vm, a[0], a[1]);
    return 0;
}

static uint32_t run_scan_cards(Vm *vm, const uint32_t *a)
{
    Native_Magic_ScanCards(vm, (int32_t)a[0]);
    return 0;
}

static uint32_t run_crt_memcpy(Vm *vm, const uint32_t *a)
{
    return Native_Crt_Memcpy(vm, a[0], a[1], a[2]);
}

static uint32_t run_ai_evaluate(Vm *vm, const uint32_t *a)
{
    return (uint32_t)Native_Ai_EvaluateBoard(vm, (int32_t)a[0]);
}

static uint32_t run_ai_penalize(Vm *vm, const uint32_t *a)
{
    return (uint32_t)Native_Ai_PenalizeCounterattack(vm, (int32_t)a[0], (int32_t)a[1]);
}

static uint32_t run_crt_memset(Vm *vm, const uint32_t *a)
{
    return Native_Crt_Memset(vm, a[0], a[1], a[2]);
}

static uint32_t run_ai_save(Vm *vm, const uint32_t *a)
{
    (void)a;
    Native_Ai_SaveGameState(vm);
    return 0;
}

static uint32_t run_ai_restore(Vm *vm, const uint32_t *a)
{
    (void)a;
    Native_Ai_RestoreGameState(vm);
    return 0;
}

static uint32_t run_ai_push(Vm *vm, const uint32_t *a)
{
    (void)a;
    Native_Ai_PushBoardState(vm);
    return 0;
}

static uint32_t run_ai_pop(Vm *vm, const uint32_t *a)
{
    (void)a;
    Native_Ai_PopBoardState(vm);
    return 0;
}

static uint32_t run_ai_reset_random(Vm *vm, const uint32_t *a)
{
    (void)a;
    Native_Ai_ResetRandomCursor(vm);
    return 0;
}

static uint32_t run_ai_begin_trial(Vm *vm, const uint32_t *a)
{
    (void)a;
    Native_Ai_BeginTrial(vm);
    return 0;
}

const NativeInfo NATIVE_FUNCTIONS[FN_COUNT] = {
    {FN_QUERY_CARD_ATTRIBUTE, "Magic_QueryCardAttribute", 4, 32, run_query, 0},
    {FN_IS_MANA_SOURCE, "Magic_IsManaSource", 2, 8, run_is_mana_source, 0},
    {FN_DROP_TOP_SPELL, "Magic_DropTopSpell", 0, 32, run_drop, 0},
    {FN_PUSH_SPELL_STACK, "Magic_PushSpellStack", 5, 32, run_push, 0},
    {FN_CLEAR_SPELL_STACK, "Magic_ClearSpellStack", 0, 32, run_clear, 0},
    {FN_GET_COLOR_AND_TYPE_FLAGS, "Card_GetColorAndTypeFlags", 2, 32, run_color_flags, 0},
    {FN_PUSH_EVENT_CONTEXT, "Magic_PushEventContext", 0, 0, run_push_event_context, 0},
    {FN_POP_EVENT_CONTEXT, "Magic_PopEventContext", 0, 0, run_pop_event_context, 0},
    {FN_CARD_IS_IN_PLAY, "Card_IsInPlay", 2, 8, run_is_tapped, 0},
    {FN_COLOR_MASK_TO_INDEX, "Card_ColorMaskToColorIndex", 1, 32, run_mask_to_index, 0},
    {FN_REMAP_COLOR_INDEX_FF, "Card_RemapColorIndexFF", 3, 32, run_remap_ff, 0},
    {FN_REMAP_COLOR_INDEX_F9, "Card_RemapColorIndexF9", 3, 32, run_remap_f9, 0},
    {FN_AI_RECORD_CHOICE, "Ai_RecordChoice", 0, 0, run_ai_record, 0},
    {FN_AI_REPLAY_CHOICE, "Ai_ReplayChoice", 0, 0, run_ai_replay, 0},
    {FN_AI_COMMIT_BEST_PLAN, "Ai_CommitBestPlan", 0, 0, run_ai_commit, 0},
    {FN_AI_CLEAR_PLAN, "Ai_ClearPlan", 0, 0, run_ai_clear, 0},
    {FN_AI_GET_PLAN_CURSOR, "Ai_GetPlanCursor", 0, 32, run_ai_cursor, 0},
    {FN_AI_PLAN_CURSOR_BACK, "Ai_PlanCursorBack", 0, 0, run_ai_cursor_back, 0},
    {FN_AI_PEEK_PLANNED_SLOT, "Ai_PeekPlannedSlot", 1, 32, run_ai_peek_slot, 0},
    {FN_AI_PEEK_PLANNED_CHOICE, "Ai_PeekPlannedChoice", 1, 32, run_ai_peek_choice, 0},
    {FN_AI_GET_LAND_COLOR_MASKS, "Ai_GetLandColorMasks", 2, 0, run_ai_land_masks, 0},
    {FN_SCAN_CARDS, "Magic_ScanCards", 1, 0, run_scan_cards, 0},
    {FN_CRT_MEMCPY, "Crt_Memcpy", 3, 32, run_crt_memcpy, 1},
    {FN_AI_SAVE_GAME_STATE, "Ai_SaveGameState", 0, 0, run_ai_save, 1},
    {FN_AI_RESTORE_GAME_STATE, "Ai_RestoreGameState", 0, 0, run_ai_restore, 1},
    {FN_AI_PUSH_BOARD_STATE, "Ai_PushBoardState", 0, 0, run_ai_push, 1},
    {FN_AI_POP_BOARD_STATE, "Ai_PopBoardState", 0, 0, run_ai_pop, 1},
    {FN_AI_RESET_RANDOM_CURSOR, "Ai_ResetRandomCursor", 0, 0, run_ai_reset_random, 1},
    {FN_AI_BEGIN_TRIAL, "Ai_BeginTrial", 0, 0, run_ai_begin_trial, 1},
    {FN_CRT_MEMSET, "Crt_Memset", 3, 32, run_crt_memset, 1},
    {FN_AI_EVALUATE_BOARD, "Ai_EvaluateBoard", 1, 32, run_ai_evaluate, 0},
    {FN_AI_PENALIZE_COUNTERATTACK, "Ai_PenalizeCounterattack", 2, 32, run_ai_penalize, 0},
};

const NativeInfo *native_find(const char *name)
{
    int i;
    for (i = 0; i < FN_COUNT; i++)
        if (strcmp(NATIVE_FUNCTIONS[i].name, name) == 0)
            return &NATIVE_FUNCTIONS[i];
    return NULL;
}
