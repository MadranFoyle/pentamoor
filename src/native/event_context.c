/*
 * event_context.c - Magic_PushEventContext and Magic_PopEventContext.
 *
 * MAGIC.EXE 0x00474428 / 0x004744de, DUEL.EXE 0x0048cac9 / 0x0048cb7f. The card-event machinery keeps
 * its "current event" in seven globals (source player and slot, card id, card colour mask, target player
 * and slot, result). Entering a nested event saves them as a frame on a 32-deep stack; leaving restores them.
 * Written from the decompiled bodies; both programs' bodies are identical apart from addresses.
 */
#include "engine.h"

#define CONTEXT_MAX 0x20
#define FRAME_SIZE 0x28u /* ten dwords per frame, seven used */

static uint32_t frame_field(const Vm *vm, int32_t depth, uint32_t index)
{
    return vm->L->event_context_stack + (uint32_t)depth * FRAME_SIZE + index * 4u;
}

void Native_Magic_PushEventContext(Vm *vm)
{
    NATIVE_ENTER(FN_PUSH_EVENT_CONTEXT);
    Mem *m = vm->mem;
    const Layout *L = vm->L;
    int32_t depth = (int32_t)mem_rd32(m, L->event_context_depth);

    if (depth < CONTEXT_MAX) {
        mem_wr32(m, frame_field(vm, depth, 0), mem_rd32(m, L->event_source_player));
        mem_wr32(m, frame_field(vm, depth, 1), mem_rd32(m, L->event_source_slot));
        mem_wr32(m, frame_field(vm, depth, 2), mem_rd32(m, L->event_card_id));
        mem_wr32(m, frame_field(vm, depth, 3), mem_rd32(m, L->event_card_color));
        mem_wr32(m, frame_field(vm, depth, 4), mem_rd32(m, L->event_target_player));
        mem_wr32(m, frame_field(vm, depth, 5), mem_rd32(m, L->event_target_slot));
        mem_wr32(m, frame_field(vm, depth, 6), mem_rd32(m, L->card_event_result));
        mem_wr32(m, L->event_context_depth, (uint32_t)(depth + 1));
    }
}

void Native_Magic_PopEventContext(Vm *vm)
{
    NATIVE_ENTER(FN_POP_EVENT_CONTEXT);
    Mem *m = vm->mem;
    const Layout *L = vm->L;
    int32_t depth = (int32_t)mem_rd32(m, L->event_context_depth);

    if (0 < depth) {
        depth = depth - 1;
        mem_wr32(m, L->event_context_depth, (uint32_t)depth);
    }
    /* With nothing saved the original still copies frame 0 back into the globals. */
    mem_wr32(m, L->event_source_player, mem_rd32(m, frame_field(vm, depth, 0)));
    mem_wr32(m, L->event_source_slot, mem_rd32(m, frame_field(vm, depth, 1)));
    mem_wr32(m, L->event_card_id, mem_rd32(m, frame_field(vm, depth, 2)));
    mem_wr32(m, L->event_card_color, mem_rd32(m, frame_field(vm, depth, 3)));
    mem_wr32(m, L->event_target_player, mem_rd32(m, frame_field(vm, depth, 4)));
    mem_wr32(m, L->event_target_slot, mem_rd32(m, frame_field(vm, depth, 5)));
    mem_wr32(m, L->card_event_result, mem_rd32(m, frame_field(vm, depth, 6)));
}
