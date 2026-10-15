/*
 * spell_stack.c - the spell stack: Magic_PushSpellStack, Magic_DropTopSpell, Magic_ClearSpellStack.
 *
 * MAGIC.EXE 0x004751d7 / 0x00475bb0 / 0x00474d1e, DUEL.EXE 0x0048d878 / 0x0048e251 / 0x0048d3bf.
 * The stack holds up to 32 pending card events. Each has a packed entry (card index, event code
 * << 16, target slot << 24), an object pair (player, slot) in a -1 terminated list, an aux pair, the
 * step it was pushed in, and the push's flags. See docs/SYMBOL_VERIFICATION.md, "The spell stack".
 */
#include "engine.h"

#define STACK_MAX 0x20

static uint32_t object_player_addr(const Vm *vm, int32_t i)
{
    return vm->L->spell_stack_objects + (uint32_t)i * 8u;
}

static uint32_t object_slot_addr(const Vm *vm, int32_t i)
{
    return vm->L->spell_stack_objects + (uint32_t)i * 8u + 4u;
}

uint32_t Native_Magic_ClearSpellStack(Vm *vm)
{
    NATIVE_ENTER(FN_CLEAR_SPELL_STACK);
    mem_wr32(vm->mem, vm->L->spell_stack_count, 0);
    mem_wr32(vm->mem, vm->L->spell_stack_objects, 0xffffffffu);
    return 0;
}

uint32_t Native_Magic_DropTopSpell(Vm *vm)
{
    NATIVE_ENTER(FN_DROP_TOP_SPELL);
    Mem *m = vm->mem;
    int32_t count = (int32_t)mem_rd32(m, vm->L->spell_stack_count);

    if (0 < count) {
        int32_t player, slot;
        uint32_t card;

        count = count - 1;
        mem_wr32(m, vm->L->spell_stack_count, (uint32_t)count);
        player = (int32_t)mem_rd32(m, object_player_addr(vm, count));
        slot = (int32_t)mem_rd32(m, object_slot_addr(vm, count));
        card = slot_addr(vm, player, slot, SLOT_CARD);
        /* A stand-in object still holding the placeholder card is freed. */
        if (mem_rd32(m, vm->L->stack_object_card_id) == mem_rd32(m, card))
            mem_wr32(m, card, 0xffffffffu);
        mem_wr32(m, object_player_addr(vm, count), 0xffffffffu);
    }
    return 0;
}

uint32_t Native_Magic_PushSpellStack(Vm *vm, int32_t player, int32_t slot, int32_t event_code,
                                     int32_t target_slot, uint32_t flags)
{
    NATIVE_ENTER(FN_PUSH_SPELL_STACK);
    Mem *m = vm->mem;
    const Layout *L = vm->L;
    int32_t count = (int32_t)mem_rd32(m, L->spell_stack_count);
    int32_t object_slot;
    int pushed;

    if (!(count < STACK_MAX))
        return 0;

    {
        uint32_t entry = L->spell_stack_entries + (uint32_t)count * 4u;
        mem_wr32(m, entry, mem_rd32(m, slot_addr(vm, player, slot, SLOT_CARD)));
        mem_wr32(m, entry, mem_rd32(m, entry) | ((uint32_t)event_code << 16));
        mem_wr32(m, entry, mem_rd32(m, entry) | ((uint32_t)target_slot << 24));
    }

    if (event_code == 0x71 || event_code == 0x7e ||
        (int32_t)mem_rd32(m, slot_addr(vm, player, slot, SLOT_CARD)) < 5) {
        /* Announcing a card (0x71), event 0x7e, or a basic land: the card itself is the object. */
        object_slot = slot;
        pushed = 1;
    } else {
        /* Otherwise a copy of the card's slot becomes a stand-in object holding the placeholder card. */
        uint32_t args[2];
        args[0] = (uint32_t)player;
        args[1] = mem_rd32(m, L->stack_object_card_id);
        object_slot = (int32_t)vm_call(vm, CALLEE_FIND_FREE_SLOT, 2, args);
        if (object_slot == -1) {
            pushed = 0;
        } else {
            uint32_t display = mem_rd32(m, slot_addr(vm, player, object_slot, SLOT_DISPLAY));
            mem_copy(m, slot_addr(vm, player, object_slot, 0), slot_addr(vm, player, slot, 0), SLOT_STRIDE);
            mem_wr32(m, slot_addr(vm, player, object_slot, SLOT_CARD), mem_rd32(m, L->stack_object_card_id));
            mem_wr32(m, slot_addr(vm, player, object_slot, SLOT_DWORD_50), 0);
            mem_wr8(m, slot_addr(vm, player, object_slot, SLOT_BYTE_20), 0);
            if ((int32_t)mem_rd32(m, slot_addr(vm, player, slot, SLOT_CARD)) == -1)
                mem_wr32(m, slot_addr(vm, player, object_slot, SLOT_ORIGINAL_CARD),
                         mem_rd32(m, slot_addr(vm, player, slot, SLOT_ORIGINAL_CARD)));
            else
                mem_wr32(m, slot_addr(vm, player, object_slot, SLOT_ORIGINAL_CARD),
                         mem_rd32(m, slot_addr(vm, player, slot, SLOT_CARD)));
            mem_wr32(m, slot_addr(vm, player, object_slot, SLOT_DWORD_44),
                     mem_rd32(m, slot_addr(vm, player, slot, SLOT_DWORD_44)));
            mem_wr32(m, slot_addr(vm, player, object_slot, SLOT_FLAGS),
                     mem_rd32(m, slot_addr(vm, player, object_slot, SLOT_FLAGS)) | 2u);
            mem_wr32(m, slot_addr(vm, player, object_slot, SLOT_STANDIN_PLAYER), (uint32_t)player);
            mem_wr32(m, slot_addr(vm, player, object_slot, SLOT_STANDIN_SLOT), (uint32_t)slot);
            mem_wr32(m, slot_addr(vm, player, object_slot, SLOT_DISPLAY), display);
            pushed = 1;
        }
    }

    if (pushed) {
        int32_t step;
        /* The original reads the global again here, after the call that may have changed it. */
        count = (int32_t)mem_rd32(m, L->spell_stack_count);
        mem_wr32(m, object_player_addr(vm, count), (uint32_t)player);
        mem_wr32(m, object_slot_addr(vm, count), (uint32_t)object_slot);
        mem_wr32(m, L->spell_stack_aux + (uint32_t)count * 8u,
                 (uint32_t)(int32_t)(int8_t)mem_rd8(m, slot_addr(vm, player, slot, SLOT_CHAR_12)));
        mem_wr32(m, L->spell_stack_aux + (uint32_t)count * 8u + 4u,
                 mem_rd32(m, slot_addr(vm, player, slot, SLOT_DWORD_28)));
        step = (int32_t)mem_rd32(m, L->current_step_code);
        if (step == -1)
            mem_wr32(m, L->spell_stack_step + (uint32_t)count * 4u, mem_rd32(m, L->step_fallback));
        else
            mem_wr32(m, L->spell_stack_step + (uint32_t)count * 4u, (uint32_t)step);
        if ((int32_t)mem_rd32(m, L->is_ai_thinking) != 1)
            mem_wr32(m, L->spell_stack_flags + (uint32_t)count * 4u, flags);
        count = count + 1;
        mem_wr32(m, L->spell_stack_count, (uint32_t)count);
        mem_wr32(m, object_player_addr(vm, count), 0xffffffffu);
    }
    return 0;
}
