/*
 * card_query.c - Magic_QueryCardAttribute, Magic_IsManaSource, Card_GetColorAndTypeFlags.
 *
 * MAGIC.EXE 0x00473179 / 0x00474389 / 0x004d0a42, DUEL.EXE 0x0048b81a / 0x0048ca2a / 0x004521e2.
 * Written from the decompiled bodies; what the codes return was established on the emulator
 * (docs/SYMBOL_VERIFICATION.md): 0x32 current power, 0x33 current toughness, 0x34 ability bitmask,
 * 0x3c the card's current card-table index. Codes 0x35 and 0x36 were never seen called and are not
 * implemented.
 */
#include "engine.h"

static int16_t rd_s16(Vm *vm, uint32_t addr)
{
    return (int16_t)mem_rd16(vm->mem, addr);
}

static int8_t rd_s8(Vm *vm, uint32_t addr)
{
    return (int8_t)mem_rd8(vm->mem, addr);
}

/* 0x800 << ((c - 1) & 31) with c a char, as the original computes a colour bit (c = 0 gives 0). */
static uint32_t colour_bit(uint32_t base, int8_t c)
{
    return base << (((uint32_t)(int32_t)c - 1u) & 0x1fu);
}

uint32_t Native_Magic_IsManaSource(Vm *vm, int32_t player, int32_t slot)
{
    NATIVE_ENTER(FN_IS_MANA_SOURCE);
    int32_t card = (int32_t)mem_rd32(vm->mem, slot_addr(vm, player, slot, SLOT_CARD));
    if ((mem_rd8(vm->mem, master_addr(vm, card, MASTER_FLAGS + 1)) & 0x10) == 0)
        return 0;
    return (mem_rd8(vm->mem, master_addr(vm, card, MASTER_FLAGS)) & 1) == 0;
}

uint32_t Native_Card_GetColorAndTypeFlags(Vm *vm, int32_t player, int32_t slot)
{
    NATIVE_ENTER(FN_GET_COLOR_AND_TYPE_FLAGS);
    Mem *m = vm->mem;
    int32_t card = (int32_t)mem_rd32(m, slot_addr(vm, player, slot, SLOT_CARD));
    uint32_t type_bit;
    int32_t index;
    uint8_t type;
    int8_t colour;

    /* A stand-in object reports the card it stands for. */
    if (card == (int32_t)mem_rd32(m, vm->L->stack_object_card_id))
        card = (int32_t)mem_rd32(m, slot_addr(vm, player, slot, SLOT_ORIGINAL_CARD));

    type = mem_rd8(m, master_addr(vm, card, MASTER_TYPE));
    if (type & 0x04)
        type_bit = 0x20000;
    else if (type & 0x10)
        type_bit = 0x40000;
    else if (type & 0x20)
        type_bit = 0x80000;
    else if (type & 0x08)
        type_bit = 0x100000;
    else
        type_bit = 0;

    index = (int32_t)Native_Card_ColorMaskToColorIndex(mem_rd8(m, slot_addr(vm, player, slot, SLOT_COLOR_MASK)));
    colour = (int8_t)Native_Card_RemapColorIndexF9(vm, player, slot, index);
    return colour_bit(0x800u, colour) | type_bit;
}

uint32_t Native_Magic_QueryCardAttribute(Vm *vm, int32_t player, int32_t slot, int32_t event_code,
                                         uint32_t target_slot)
{
    NATIVE_ENTER(FN_QUERY_CARD_ATTRIBUTE);
    Mem *m = vm->mem;
    const Layout *L = vm->L;
    uint32_t saved, result, local = 0, args[3] = {0, 0, 0};
    int32_t card;
    int recompute = 0; /* the decompiler's 0x004737a0: store `local` as the result, let cards adjust it */

#define SLOT(field) slot_addr(vm, player, slot, (field))

    saved = mem_rd32(m, L->query_saved);
    mem_wr32(m, L->query_counter, mem_rd32(m, L->query_counter) + 1);
    if (mem_rd32(m, L->event_depth) != 0)
        Native_Magic_PushEventContext(vm);
    mem_wr32(m, L->event_source_player, (uint32_t)player);
    mem_wr32(m, L->event_source_slot, (uint32_t)slot);
    mem_wr32(m, L->event_card_id, mem_rd32(m, SLOT(SLOT_CARD)));
    card = (int32_t)mem_rd32(m, L->event_card_id);
    mem_wr32(m, L->event_card_color, (uint32_t)(int32_t)rd_s8(vm, master_addr(vm, card, MASTER_COLOR)));
    mem_wr32(m, L->event_target_slot, target_slot);

    switch (event_code) {
    case 0x32: /* power: printed + modifier, or the cached value */
        card = (int32_t)mem_rd32(m, L->event_card_id);
        if ((mem_rd8(m, SLOT(SLOT_FLAGS)) & 2) == 0)
            local = (uint32_t)(int32_t)rd_s16(vm, master_addr(vm, card, MASTER_POWER));
        else
            local = (uint32_t)(int32_t)rd_s16(vm, master_addr(vm, card, MASTER_POWER)) & 0xffffbfffu;
        local = local + (uint32_t)(int32_t)rd_s16(vm, SLOT(SLOT_POWER_MOD));
        if (mem_rd8(m, SLOT(SLOT_ABILITIES2 + 3)) & 4) {
            mem_wr32(m, SLOT(SLOT_ABILITIES2), mem_rd32(m, SLOT(SLOT_ABILITIES2)) & 0xfbffffffu);
            recompute = 1;
        } else {
            mem_wr32(m, L->card_event_result, (uint32_t)(int32_t)rd_s16(vm, SLOT(SLOT_POWER_CACHE)));
        }
        break;
    case 0x33: /* toughness */
        card = (int32_t)mem_rd32(m, L->event_card_id);
        if ((mem_rd8(m, SLOT(SLOT_FLAGS)) & 2) == 0)
            local = (uint32_t)(int32_t)rd_s16(vm, master_addr(vm, card, MASTER_TOUGHNESS));
        else
            local = (uint32_t)(int32_t)rd_s16(vm, master_addr(vm, card, MASTER_TOUGHNESS)) & 0xffffbfffu;
        local = local + (uint32_t)(int32_t)rd_s16(vm, SLOT(SLOT_TOUGH_MOD));
        if (mem_rd8(m, SLOT(SLOT_ABILITIES2 + 3)) & 2) {
            mem_wr32(m, SLOT(SLOT_ABILITIES2), mem_rd32(m, SLOT(SLOT_ABILITIES2)) & 0xfdffffffu);
            recompute = 1;
        } else {
            mem_wr32(m, L->card_event_result, (uint32_t)(int32_t)rd_s16(vm, SLOT(SLOT_TOUGH_CACHE)));
        }
        break;
    case 0x34: { /* ability bitmask */
        uint32_t current = mem_rd32(m, SLOT(SLOT_ABILITIES2));
        uint32_t printed;
        card = (int32_t)mem_rd32(m, L->event_card_id);
        printed = mem_rd32(m, master_addr(vm, card, MASTER_ABILITIES));
        local = (current & 0x7000000u) | printed;
        if (printed & 0x1ff81fu) {
            /* Colour-keyed abilities (bits 0-4 and 11-15) are remapped through the colour overrides. */
            uint32_t remapped = 0;
            int32_t i;
            for (i = 0; i < 5; i++) {
                if (local & (1u << (i & 0x1f)))
                    remapped |= colour_bit(1u, (int8_t)Native_Card_RemapColorIndexFF(vm, player, slot, i + 1));
                if (local & (0x800u << (i & 0x1f)))
                    remapped |= colour_bit(0x800u, (int8_t)Native_Card_RemapColorIndexF9(vm, player, slot, i + 1));
            }
            local = (current & 0x7000000u) | (printed & 0xffe007e0u) | remapped;
        }
        if (mem_rd8(m, SLOT(SLOT_ABILITIES2 + 3)) & 8) {
            mem_wr32(m, SLOT(SLOT_ABILITIES2), mem_rd32(m, SLOT(SLOT_ABILITIES2)) & 0xf7ffffffu);
            recompute = 1;
        } else {
            mem_wr32(m, L->card_event_result, mem_rd32(m, SLOT(SLOT_ABILITIES2)));
        }
        break;
    }
    case 0x35:
        NATIVE_UNIMPLEMENTED("Magic_QueryCardAttribute: event code 0x35 (never seen called)");
        return 0;
    case 0x36:
        NATIVE_UNIMPLEMENTED("Magic_QueryCardAttribute: event code 0x36 (never seen called)");
        return 0;
    case 0x3c: { /* the card's current card-table index */
        int32_t current = (int32_t)mem_rd32(m, SLOT(SLOT_CARD));
        int32_t token_base = (int32_t)mem_rd32(m, L->token_card_base);
        if ((current < token_base || token_base + 0x1d <= current) && current != -1) {
            local = mem_rd32(m, SLOT(SLOT_ORIGINAL_CARD));
            if (mem_rd8(m, SLOT(SLOT_ABILITIES2 + 3)) & 1) {
                /* A copy or transformation ends: put the original card back. */
                mem_wr32(m, SLOT(SLOT_CARD), mem_rd32(m, SLOT(SLOT_ORIGINAL_CARD)));
                mem_wr32(m, SLOT(SLOT_ABILITIES2), mem_rd32(m, SLOT(SLOT_ABILITIES2)) & 0xfeffffffu);
                mem_wr8(m, SLOT(SLOT_BYTE_11F), 0);
                recompute = 1;
            } else {
                mem_wr32(m, L->card_event_result, mem_rd32(m, SLOT(SLOT_CARD)));
            }
        } else {
            mem_wr32(m, L->card_event_result, mem_rd32(m, SLOT(SLOT_CARD)));
        }
        break;
    }
    default:
        NATIVE_UNIMPLEMENTED("Magic_QueryCardAttribute: event code other than 0x32-0x36 and 0x3c");
        return 0;
    }

    if (recompute) {
        mem_wr32(m, L->card_event_result, local);
        if (mem_rd32(m, L->event_depth) != 0) {
            /* Inside an event every card may adjust the value (g_CardEventResult). */
            Native_Magic_ScanCards(vm, event_code);
            if (mem_rd32(m, L->duel_mode_flags) & 0x10000u) {
                mem_wr32(m, L->duel_mode_flags, mem_rd32(m, L->duel_mode_flags) & 0xfffeffffu);
                mem_wr32(m, SLOT(SLOT_CARD), mem_rd32(m, L->card_event_result));
                mem_wr32(m, L->duel_mode_flags, mem_rd32(m, L->duel_mode_flags) | 0x20000u);
                Native_Magic_ScanCards(vm, event_code);
                mem_wr32(m, L->duel_mode_flags, mem_rd32(m, L->duel_mode_flags) & 0xfffdffffu);
            }
        }
        if (event_code == 0x32) {
            if ((int32_t)mem_rd32(m, L->card_event_result) < 0)
                mem_wr32(m, L->card_event_result, 0);
            if (mem_rd8(m, SLOT(SLOT_ABILITIES1 + 1)) & 0x40)
                mem_wr32(m, L->card_event_result, mem_rd32(m, L->card_event_result) << 1);
        }
    }

    result = mem_rd32(m, L->card_event_result);

    /* A tapped creature whose toughness no longer exceeds the damage field is marked (0x33 only). */
    args[0] = (uint32_t)player;
    args[1] = (uint32_t)slot;
    if (Native_Card_IsInPlay(vm, player, slot) != 0 && event_code == 0x33) {
        card = (int32_t)mem_rd32(m, L->event_card_id);
        if ((mem_rd8(m, master_addr(vm, card, MASTER_TYPE)) & 2) != 0 &&
            ((int32_t)result < 1 || (int32_t)result <= (int32_t)rd_s16(vm, SLOT(SLOT_S16_10))) &&
            (int32_t)mem_rd32(m, L->current_step_code) == -1 &&
            (mem_rd32(m, L->duel_mode_flags) & 0x204u) == 0) {
            args[0] = (uint32_t)player;
            args[1] = (uint32_t)slot;
            args[2] = 2;
            vm_call(vm, CALLEE_MARK_CARD, 3, args);
            vm_call(vm, CALLEE_AFTER_MARK, 0, args);
        }
    }
    if (mem_rd32(m, L->event_depth) != 0)
        Native_Magic_PopEventContext(vm);

    if (event_code == 0x32)
        mem_wr16(m, SLOT(SLOT_POWER_CACHE), (uint16_t)result);
    if (event_code == 0x33)
        mem_wr16(m, SLOT(SLOT_TOUGH_CACHE), (uint16_t)result);
    if (event_code == 0x34)
        mem_wr32(m, SLOT(SLOT_ABILITIES2), result);
    if (event_code != 0x3c) {
        mem_wr32(m, L->query_saved, saved);
        return result;
    }

    /* 0x3c: install the (possibly restored) card and refresh its colour byte. */
    mem_wr32(m, SLOT(SLOT_CARD), result);
    if (mem_rd8(m, master_addr(vm, (int32_t)result, MASTER_FLAGS + 1)) & 0x10) {
        int32_t id = (int32_t)mem_rd32(m, master_addr(vm, (int32_t)result, MASTER_CARD_ID));
        int keep = 0;
        if (id < 0x12d) {
            if (id == 300) {
                mem_wr8(m, SLOT(SLOT_COLOR_BYTE), 1);
                keep = 1;
            } else if (id == 0xf) {
                mem_wr8(m, SLOT(SLOT_COLOR_BYTE), 0x3e);
                keep = 1;
            }
        } else if (id == 0x13e || id == 0x366) {
            keep = 1;
        }
        if (!keep)
            mem_wr8(m, SLOT(SLOT_COLOR_BYTE), mem_rd8(m, master_addr(vm, (int32_t)result, MASTER_COLOR)));
    }
    if ((mem_rd8(m, SLOT(SLOT_ABILITIES1)) & 0x40) != 0 &&
        (mem_rd8(m, master_addr(vm, (int32_t)mem_rd32(m, SLOT(SLOT_CARD)), MASTER_TYPE)) & 2) == 0) {
        /* No longer a creature: mark the enchantments attached to it whose card info field is 0x2d. */
        int32_t p, s;
        for (p = 0; p < 2; p++) {
            for (s = 0; s < (int32_t)mem_rd32(m, L->player_card_count + (uint32_t)p * 4u); s++) {
                int32_t other = (int32_t)mem_rd32(m, slot_addr(vm, p, s, SLOT_CARD));
                if (other != -1 &&
                    (mem_rd8(m, slot_addr(vm, p, s, SLOT_FLAGS)) & 2) != 0 &&
                    (int32_t)rd_s8(vm, slot_addr(vm, p, s, SLOT_CHAR_12)) == player &&
                    (int32_t)mem_rd32(m, slot_addr(vm, p, s, SLOT_DWORD_28)) == slot &&
                    (mem_rd8(m, master_addr(vm, other, MASTER_TYPE)) & 4) != 0 &&
                    mem_rd32(m, L->card_info_base + 0x14u +
                                    mem_rd32(m, master_addr(vm, other, MASTER_CARD_ID)) * CARD_INFO_STRIDE) == 0x2d) {
                    args[0] = (uint32_t)p;
                    args[1] = (uint32_t)s;
                    args[2] = 3;
                    vm_call(vm, CALLEE_MARK_CARD, 3, args);
                }
            }
        }
    }
    mem_wr32(m, L->query_saved, saved);
    return result;
#undef SLOT
}
