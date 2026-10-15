/*
 * card_util.c - small card-slot helpers: Card_IsInPlay, Card_ColorMaskToColorIndex and the two
 * colour-remap lookups.
 *
 * MAGIC.EXE 0x00471c32 / 0x00473cc5 / 0x0041d9d2 / 0x0041d963, DUEL.EXE 0x0048a33f / 0x0048c367 /
 * 0x004af7bb / 0x004af74c. Written from the decompiled bodies (identical in both programs apart
 * from addresses). The decompiler's names for three of them were wrong. Card_IsInPlay was Card_IsTapped,
 * but recorded calls show it returns 1 for flags 0x30882 (untapped) and 0x30892 (the same plus the tap
 * bit) and 0 only for cards not in play: it ignores tapping. The two remap lookups were Card_UntapCard /
 * Card_SetTapState (MAGIC) and Duel_GetCardModifiedPower / Duel_GetCardColorOverride (DUEL); they are named
 * by what the body does (static; no remap byte was ever non-zero in the recorded games).
 */
#include "engine.h"

uint32_t Native_Card_IsInPlay(Vm *vm, int32_t player, int32_t slot)
{
    NATIVE_ENTER(FN_CARD_IS_IN_PLAY);
    if ((int32_t)mem_rd32(vm->mem, slot_addr(vm, player, slot, SLOT_CARD)) == -1)
        return 0;
    /* The original reads the flags dword and tests its low byte: bit 1 (in play) set and bit 5 clear. Bit 5
     * never appeared together with bit 1 in the recorded games, so that half of the test is static only. */
    return ((uint8_t)mem_rd32(vm->mem, slot_addr(vm, player, slot, SLOT_FLAGS)) & 0x22u) == 2u;
}

/* The lowest set bit among colour-mask bits 1 to 5 as an index 1 to 5; 0 if none (the argument is a byte). */
uint32_t Native_Card_ColorMaskToColorIndex(uint32_t mask)
{
    NATIVE_ENTER(FN_COLOR_MASK_TO_INDEX);
    uint8_t v = (uint8_t)mask;

    if (v & 0x02)
        return 1;
    if (v & 0x04)
        return 2;
    if (v & 0x08)
        return 3;
    if (v & 0x10)
        return 4;
    if (v & 0x20)
        return 5;
    return 0;
}

static int32_t remap(Vm *vm, int32_t player, int32_t slot, int32_t index, uint32_t table)
{
    int8_t b = (int8_t)mem_rd8(vm->mem, slot_addr(vm, player, slot, table + (uint32_t)index));

    return b != 0 ? (int32_t)b : index;
}

int32_t Native_Card_RemapColorIndexF9(Vm *vm, int32_t player, int32_t slot, int32_t index)
{
    NATIVE_ENTER(FN_REMAP_COLOR_INDEX_F9);
    return remap(vm, player, slot, index, 0xf9u);
}

int32_t Native_Card_RemapColorIndexFF(Vm *vm, int32_t player, int32_t slot, int32_t index)
{
    NATIVE_ENTER(FN_REMAP_COLOR_INDEX_FF);
    return remap(vm, player, slot, index, 0xffu);
}
