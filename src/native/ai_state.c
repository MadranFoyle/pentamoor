/*
 * ai_state.c - the AI's snapshots of the game, and the start of a trial.
 *
 * The AI plays by random rollouts (docs/SYMBOL_VERIFICATION.md, "The AI"). Before it searches it saves the whole game
 * (Ai_SaveGameState); before every trial it puts it back (Ai_RestoreGameState, called by Ai_BeginTrial, about 2,500 times in a
 * search). The saved game is a fixed list of regions (the card slots, the master record of the card the search is about, the
 * life totals, the spell stack, the AI's own plan lists, ...) copied to a second area, and a few single words. Ai_PushBoardState
 * and Ai_PopBoardState are a second snapshot of nearly the same regions in another area, one deep.
 *
 * Each of the four is a list of steps (below), run in the original's order. The lists were read off the machine code of both
 * programs (the two programs' functions were lined up by their code), because the names a decompiler gave these globals are not
 * reliable; `docs/SYMBOL_VERIFICATION.md` has what is known of what each region is.
 *
 * Instruction counts: a native function adds to native_cost_extra the number of instructions its original's own code runs, so
 * that a hosted run can spend as many (winemu `--native-exact`). Here that is a constant per function (the code is straight
 * line); the C runtime's memcpy it calls adds its own.
 */
#include "engine.h"

typedef enum {
    SNAP_COPY,                 /* memcpy(dst, src, size) */
    SNAP_MASTER_RECORD,        /* memcpy(dst, master record of card index g_MasterCardCount, size): the record just past the table */
    SNAP_MASTER_RECORD_BACK,   /* memcpy(master record of card index g_MasterCardCount, src, size) */
    SNAP_WORD,                 /* *dst = *src (a dword) */
    SNAP_STORE,                /* *dst = value (src field) */
    SNAP_ASSERT_NONNEG,        /* assert(*dst >= 0): sid\Ai.c */
    SNAP_CALL                  /* a call: Ai_ResetRandomCursor runs native, the table of random numbers is filled by the original */
} SnapKind;

typedef struct {
    SnapKind kind;
    uint32_t dst, src, size;
} SnapStep;

static const SnapStep SAVE_DUEL[] = {
    {SNAP_STORE, 0x00515e60u, 0x00000000u, 4},
    {SNAP_COPY, 0x0066ab10u, 0x006826c0u, 0xb640u},
    {SNAP_MASTER_RECORD, 0x00676170u, 0, 0x340u},   /* the master record at g_MasterCardCount, to the snapshot */
    {SNAP_COPY, 0x00513588u, 0x006669f0u, 0xfa0u},
    {SNAP_COPY, 0x0050dd50u, 0x0068f370u, 0xfa0u},
    {SNAP_COPY, 0x0050bb58u, 0x0068dd10u, 0xfa0u},
    {SNAP_COPY, 0x0050dd10u, 0x0068ed10u, 0x40u},
    {SNAP_COPY, 0x0050dcc8u, 0x0068f2e0u, 0x40u},
    {SNAP_COPY, 0x00514e38u, 0x0068ef50u, 0x40u},
    {SNAP_COPY, 0x005127d8u, 0x00666570u, 0x198u},
    {SNAP_COPY, 0x00512970u, 0x00681ea8u, 0x8u},
    {SNAP_COPY, 0x00513580u, 0x006668f0u, 0x8u},
    {SNAP_COPY, 0x00514638u, 0x0066aad0u, 0x8u},
    {SNAP_COPY, 0x00514630u, 0x006664f0u, 0x8u},
    {SNAP_COPY, 0x0050f6d8u, 0x0068ee70u, 0x60u},
    {SNAP_COPY, 0x0050ecf0u, 0x0068ed50u, 0x80u},
    {SNAP_COPY, 0x00511ef0u, 0x00690320u, 0x7d0u},
    {SNAP_COPY, 0x00510e30u, 0x00681ee0u, 0x7d0u},
    {SNAP_WORD, 0x00514eb8u, 0x00681eb0u, 4},
    {SNAP_WORD, 0x0050f9b8u, 0x0068f2c4u, 4},
    {SNAP_WORD, 0x006c1214u, 0x0050f9b8u, 4},
    {SNAP_WORD, 0x00514528u, 0x0066644cu, 4},
    {SNAP_WORD, 0x005126d4u, 0x006826b0u, 4},
    {SNAP_WORD, 0x0050b378u, 0x00681ea4u, 4},
    {SNAP_COPY, 0x00511e70u, 0x0068f240u, 0x80u},
    {SNAP_COPY, 0x00514530u, 0x0068efb0u, 0x100u},
    {SNAP_COPY, 0x0050f840u, 0x0068f120u, 0x100u},
    {SNAP_COPY, 0x00514e30u, 0x00666408u, 0x8u},
    {SNAP_ASSERT_NONNEG, 0x006764b8u, 0, 4},   /* sid\Ai.c line 0x176: the spell stack count is not negative */
    {SNAP_WORD, 0x0050db20u, 0x006764b8u, 4},
    {SNAP_WORD, 0x0050f6b0u, 0x00666760u, 4},
    {SNAP_WORD, 0x00511e04u, 0x00690318u, 4},
    {SNAP_COPY, 0x0050f570u, 0x00690b00u, 0x140u},
    {SNAP_COPY, 0x0050f988u, 0x00676150u, 0x20u},
    {SNAP_COPY, 0x0050f6b8u, 0x0068ece0u, 0x1cu},
    {SNAP_CALL, 0x004398beu, 0, 0},
};

static const SnapStep RESTORE_DUEL[] = {
    {SNAP_COPY, 0x006826c0u, 0x0066ab10u, 0xb640u},
    {SNAP_MASTER_RECORD_BACK, 0, 0x00676170u, 0x340u},   /* and back */
    {SNAP_COPY, 0x006669f0u, 0x00513588u, 0xfa0u},
    {SNAP_COPY, 0x0068f370u, 0x0050dd50u, 0xfa0u},
    {SNAP_COPY, 0x0068dd10u, 0x0050bb58u, 0xfa0u},
    {SNAP_COPY, 0x0068ed10u, 0x0050dd10u, 0x40u},
    {SNAP_COPY, 0x0068f2e0u, 0x0050dcc8u, 0x40u},
    {SNAP_COPY, 0x0068ef50u, 0x00514e38u, 0x40u},
    {SNAP_COPY, 0x00666570u, 0x005127d8u, 0x198u},
    {SNAP_COPY, 0x00681ea8u, 0x00512970u, 0x8u},
    {SNAP_COPY, 0x006668f0u, 0x00513580u, 0x8u},
    {SNAP_COPY, 0x0066aad0u, 0x00514638u, 0x8u},
    {SNAP_COPY, 0x006664f0u, 0x00514630u, 0x8u},
    {SNAP_COPY, 0x0068ee70u, 0x0050f6d8u, 0x60u},
    {SNAP_COPY, 0x0068ed50u, 0x0050ecf0u, 0x80u},
    {SNAP_COPY, 0x00690320u, 0x00511ef0u, 0x7d0u},
    {SNAP_COPY, 0x00681ee0u, 0x00510e30u, 0x7d0u},
    {SNAP_WORD, 0x00681eb0u, 0x00514eb8u, 4},
    {SNAP_WORD, 0x0068f2c4u, 0x0050f9b8u, 4},
    {SNAP_WORD, 0x0066644cu, 0x00514528u, 4},
    {SNAP_WORD, 0x006826b0u, 0x005126d4u, 4},
    {SNAP_WORD, 0x00681ea4u, 0x0050b378u, 4},
    {SNAP_COPY, 0x0068f240u, 0x00511e70u, 0x80u},
    {SNAP_COPY, 0x0068efb0u, 0x00514530u, 0x100u},
    {SNAP_COPY, 0x0068f120u, 0x0050f840u, 0x100u},
    {SNAP_COPY, 0x00666408u, 0x00514e30u, 0x8u},
    {SNAP_WORD, 0x006764b8u, 0x0050db20u, 4},
    {SNAP_WORD, 0x00666760u, 0x0050f6b0u, 4},
    {SNAP_WORD, 0x00690318u, 0x00511e04u, 4},
    {SNAP_COPY, 0x00690b00u, 0x0050f570u, 0x140u},
    {SNAP_COPY, 0x00676150u, 0x0050f988u, 0x20u},
    {SNAP_COPY, 0x0068ece0u, 0x0050f6b8u, 0x1cu},
    {SNAP_CALL, 0x004398feu, 0, 0},
};

static const SnapStep PUSH_DUEL[] = {
    {SNAP_COPY, 0x00676520u, 0x006826c0u, 0xb640u},
    {SNAP_MASTER_RECORD, 0x00681b60u, 0, 0x340u},   /* the master record at g_MasterCardCount, to the snapshot */
    {SNAP_COPY, 0x0050cb80u, 0x006669f0u, 0xfa0u},
    {SNAP_COPY, 0x0050fa10u, 0x0068f370u, 0xfa0u},
    {SNAP_COPY, 0x00514ec0u, 0x0068dd10u, 0xfa0u},
    {SNAP_COPY, 0x00514e78u, 0x0068ed10u, 0x40u},
    {SNAP_COPY, 0x0050f9d0u, 0x0068f2e0u, 0x40u},
    {SNAP_COPY, 0x0050f940u, 0x0068ef50u, 0x40u},
    {SNAP_COPY, 0x0050db28u, 0x00666570u, 0x198u},
    {SNAP_COPY, 0x0050b380u, 0x00681ea8u, 0x8u},
    {SNAP_COPY, 0x0050f980u, 0x006668f0u, 0x8u},
    {SNAP_COPY, 0x0050f9a8u, 0x0066aad0u, 0x8u},
    {SNAP_COPY, 0x0050f9b0u, 0x006664f0u, 0x8u},
    {SNAP_COPY, 0x00511e08u, 0x0068ee70u, 0x60u},
    {SNAP_COPY, 0x005109b0u, 0x0068ed50u, 0x80u},
    {SNAP_COPY, 0x00514640u, 0x00690320u, 0x7d0u},
    {SNAP_COPY, 0x0050b388u, 0x00681ee0u, 0x7d0u},
    {SNAP_WORD, 0x0050f838u, 0x00681eb0u, 4},
    {SNAP_WORD, 0x00513578u, 0x0068f2c4u, 4},
    {SNAP_WORD, 0x0050f9bcu, 0x0066644cu, 4},
    {SNAP_WORD, 0x0050f9c8u, 0x006826b0u, 4},
    {SNAP_WORD, 0x00511e68u, 0x00681ea4u, 4},
    {SNAP_COPY, 0x0050caf8u, 0x0068f240u, 0x80u},
    {SNAP_COPY, 0x005126d8u, 0x0068efb0u, 0x100u},
    {SNAP_COPY, 0x0050f738u, 0x0068f120u, 0x100u},
    {SNAP_COPY, 0x0050f9c0u, 0x00666408u, 0x8u},
    {SNAP_WORD, 0x005126c0u, 0x006764b8u, 4},
    {SNAP_WORD, 0x0050dd08u, 0x00666760u, 4},
    {SNAP_WORD, 0x0050dcc0u, 0x0068f2d4u, 4},
    {SNAP_COPY, 0x00514e10u, 0x0068ece0u, 0x1cu},
};

static const SnapStep POP_DUEL[] = {
    {SNAP_COPY, 0x006826c0u, 0x00676520u, 0xb640u},
    {SNAP_MASTER_RECORD_BACK, 0, 0x00681b60u, 0x340u},   /* and back */
    {SNAP_COPY, 0x006669f0u, 0x0050cb80u, 0xfa0u},
    {SNAP_COPY, 0x0068f370u, 0x0050fa10u, 0xfa0u},
    {SNAP_COPY, 0x0068dd10u, 0x00514ec0u, 0xfa0u},
    {SNAP_COPY, 0x0068ed10u, 0x00514e78u, 0x40u},
    {SNAP_COPY, 0x0068f2e0u, 0x0050f9d0u, 0x40u},
    {SNAP_COPY, 0x0068ef50u, 0x0050f940u, 0x40u},
    {SNAP_COPY, 0x00666570u, 0x0050db28u, 0x198u},
    {SNAP_COPY, 0x00681ea8u, 0x0050b380u, 0x8u},
    {SNAP_COPY, 0x006668f0u, 0x0050f980u, 0x8u},
    {SNAP_COPY, 0x0066aad0u, 0x0050f9a8u, 0x8u},
    {SNAP_COPY, 0x006664f0u, 0x0050f9b0u, 0x8u},
    {SNAP_COPY, 0x0068ee70u, 0x00511e08u, 0x60u},
    {SNAP_COPY, 0x0068ed50u, 0x005109b0u, 0x80u},
    {SNAP_COPY, 0x00690320u, 0x00514640u, 0x7d0u},
    {SNAP_COPY, 0x00681ee0u, 0x0050b388u, 0x7d0u},
    {SNAP_WORD, 0x00681eb0u, 0x0050f838u, 4},
    {SNAP_WORD, 0x0068f2c4u, 0x00513578u, 4},
    {SNAP_WORD, 0x0066644cu, 0x0050f9bcu, 4},
    {SNAP_WORD, 0x006826b0u, 0x0050f9c8u, 4},
    {SNAP_WORD, 0x00681ea4u, 0x00511e68u, 4},
    {SNAP_COPY, 0x0068f240u, 0x0050caf8u, 0x80u},
    {SNAP_COPY, 0x0068efb0u, 0x005126d8u, 0x100u},
    {SNAP_COPY, 0x0068f120u, 0x0050f738u, 0x100u},
    {SNAP_COPY, 0x00666408u, 0x0050f9c0u, 0x8u},
    {SNAP_WORD, 0x006764b8u, 0x005126c0u, 4},
    {SNAP_WORD, 0x00666760u, 0x0050dd08u, 4},
    {SNAP_WORD, 0x0068f2d4u, 0x0050dcc0u, 4},
    {SNAP_COPY, 0x0068ece0u, 0x00514e10u, 0x1cu},
};

static const SnapStep SAVE_MAGIC[] = {
    {SNAP_STORE, 0x00556928u, 0x00000000u, 4},
    {SNAP_COPY, 0x00627a90u, 0x006a5f30u, 0xb640u},
    {SNAP_MASTER_RECORD, 0x006330f0u, 0, 0x340u},   /* the master record at g_MasterCardCount, to the snapshot */
    {SNAP_COPY, 0x00554050u, 0x0069e730u, 0xfa0u},
    {SNAP_COPY, 0x0054e818u, 0x006ff710u, 0xfa0u},
    {SNAP_COPY, 0x0054c620u, 0x006b1590u, 0xfa0u},
    {SNAP_COPY, 0x0054e7d8u, 0x0063edd0u, 0x40u},
    {SNAP_COPY, 0x0054e790u, 0x0063ee90u, 0x40u},
    {SNAP_COPY, 0x00555900u, 0x0063ee30u, 0x40u},
    {SNAP_COPY, 0x005532a0u, 0x00627870u, 0x198u},
    {SNAP_COPY, 0x00553438u, 0x006a4a00u, 0x8u},
    {SNAP_COPY, 0x00554048u, 0x00696870u, 0x8u},
    {SNAP_COPY, 0x00555100u, 0x006a2828u, 0x8u},
    {SNAP_COPY, 0x005550f8u, 0x00695e00u, 0x8u},
    {SNAP_COPY, 0x005501a0u, 0x006b3000u, 0x60u},
    {SNAP_COPY, 0x0054f7b8u, 0x006b2d90u, 0x80u},
    {SNAP_COPY, 0x005529b8u, 0x007006e0u, 0x7d0u},
    {SNAP_COPY, 0x005518f8u, 0x006a5750u, 0x7d0u},
    {SNAP_WORD, 0x00555980u, 0x006a4a08u, 4},
    {SNAP_WORD, 0x00550480u, 0x006ff558u, 4},
    {SNAP_WORD, 0x006498f0u, 0x00550480u, 4},
    {SNAP_WORD, 0x00554ff0u, 0x0068a708u, 4},
    {SNAP_WORD, 0x0055319cu, 0x006a5f20u, 4},
    {SNAP_WORD, 0x0054be40u, 0x006a49fcu, 4},
    {SNAP_COPY, 0x00552938u, 0x006ff4d0u, 0x80u},
    {SNAP_COPY, 0x00554ff8u, 0x006fecc0u, 0x100u},
    {SNAP_COPY, 0x00550308u, 0x006ff390u, 0x100u},
    {SNAP_COPY, 0x005558f8u, 0x006808b8u, 0x8u},
    {SNAP_ASSERT_NONNEG, 0x006a3f78u, 0, 4},   /* sid\Ai.c line 0x176: the spell stack count is not negative */
    {SNAP_WORD, 0x0054e5e8u, 0x006a3f78u, 4},
    {SNAP_WORD, 0x00550178u, 0x00695f18u, 4},
    {SNAP_WORD, 0x005528ccu, 0x007006d4u, 4},
    {SNAP_COPY, 0x00550038u, 0x00700ec0u, 0x140u},
    {SNAP_COPY, 0x00550450u, 0x006330d0u, 0x20u},
    {SNAP_COPY, 0x00550180u, 0x006b2d40u, 0x1cu},
    {SNAP_CALL, 0x0040a1ffu, 0, 0},
};

static const SnapStep RESTORE_MAGIC[] = {
    {SNAP_COPY, 0x006a5f30u, 0x00627a90u, 0xb640u},
    {SNAP_MASTER_RECORD_BACK, 0, 0x006330f0u, 0x340u},   /* and back */
    {SNAP_COPY, 0x0069e730u, 0x00554050u, 0xfa0u},
    {SNAP_COPY, 0x006ff710u, 0x0054e818u, 0xfa0u},
    {SNAP_COPY, 0x006b1590u, 0x0054c620u, 0xfa0u},
    {SNAP_COPY, 0x0063edd0u, 0x0054e7d8u, 0x40u},
    {SNAP_COPY, 0x0063ee90u, 0x0054e790u, 0x40u},
    {SNAP_COPY, 0x0063ee30u, 0x00555900u, 0x40u},
    {SNAP_COPY, 0x00627870u, 0x005532a0u, 0x198u},
    {SNAP_COPY, 0x006a4a00u, 0x00553438u, 0x8u},
    {SNAP_COPY, 0x00696870u, 0x00554048u, 0x8u},
    {SNAP_COPY, 0x006a2828u, 0x00555100u, 0x8u},
    {SNAP_COPY, 0x00695e00u, 0x005550f8u, 0x8u},
    {SNAP_COPY, 0x006b3000u, 0x005501a0u, 0x60u},
    {SNAP_COPY, 0x006b2d90u, 0x0054f7b8u, 0x80u},
    {SNAP_COPY, 0x007006e0u, 0x005529b8u, 0x7d0u},
    {SNAP_COPY, 0x006a5750u, 0x005518f8u, 0x7d0u},
    {SNAP_WORD, 0x006a4a08u, 0x00555980u, 4},
    {SNAP_WORD, 0x006ff558u, 0x00550480u, 4},
    {SNAP_WORD, 0x0068a708u, 0x00554ff0u, 4},
    {SNAP_WORD, 0x006a5f20u, 0x0055319cu, 4},
    {SNAP_WORD, 0x006a49fcu, 0x0054be40u, 4},
    {SNAP_COPY, 0x006ff4d0u, 0x00552938u, 0x80u},
    {SNAP_COPY, 0x006fecc0u, 0x00554ff8u, 0x100u},
    {SNAP_COPY, 0x006ff390u, 0x00550308u, 0x100u},
    {SNAP_COPY, 0x006808b8u, 0x005558f8u, 0x8u},
    {SNAP_WORD, 0x006a3f78u, 0x0054e5e8u, 4},
    {SNAP_WORD, 0x00695f18u, 0x00550178u, 4},
    {SNAP_WORD, 0x007006d4u, 0x005528ccu, 4},
    {SNAP_COPY, 0x00700ec0u, 0x00550038u, 0x140u},
    {SNAP_COPY, 0x006330d0u, 0x00550450u, 0x20u},
    {SNAP_COPY, 0x006b2d40u, 0x00550180u, 0x1cu},
    {SNAP_CALL, 0x0040a240u, 0, 0},
};

static const SnapStep PUSH_MAGIC[] = {
    {SNAP_COPY, 0x00633440u, 0x006a5f30u, 0xb640u},
    {SNAP_MASTER_RECORD, 0x0063ea80u, 0, 0x340u},   /* the master record at g_MasterCardCount, to the snapshot */
    {SNAP_COPY, 0x0054d648u, 0x0069e730u, 0xfa0u},
    {SNAP_COPY, 0x005504d8u, 0x006ff710u, 0xfa0u},
    {SNAP_COPY, 0x00555988u, 0x006b1590u, 0xfa0u},
    {SNAP_COPY, 0x00555940u, 0x0063edd0u, 0x40u},
    {SNAP_COPY, 0x00550498u, 0x0063ee90u, 0x40u},
    {SNAP_COPY, 0x00550408u, 0x0063ee30u, 0x40u},
    {SNAP_COPY, 0x0054e5f0u, 0x00627870u, 0x198u},
    {SNAP_COPY, 0x0054be48u, 0x006a4a00u, 0x8u},
    {SNAP_COPY, 0x00550448u, 0x00696870u, 0x8u},
    {SNAP_COPY, 0x00550470u, 0x006a2828u, 0x8u},
    {SNAP_COPY, 0x00550478u, 0x00695e00u, 0x8u},
    {SNAP_COPY, 0x005528d0u, 0x006b3000u, 0x60u},
    {SNAP_COPY, 0x00551478u, 0x006b2d90u, 0x80u},
    {SNAP_COPY, 0x00555108u, 0x007006e0u, 0x7d0u},
    {SNAP_COPY, 0x0054be50u, 0x006a5750u, 0x7d0u},
    {SNAP_WORD, 0x00550300u, 0x006a4a08u, 4},
    {SNAP_WORD, 0x00554040u, 0x006ff558u, 4},
    {SNAP_WORD, 0x00550484u, 0x0068a708u, 4},
    {SNAP_WORD, 0x00550490u, 0x006a5f20u, 4},
    {SNAP_WORD, 0x00552930u, 0x006a49fcu, 4},
    {SNAP_COPY, 0x0054d5c0u, 0x006ff4d0u, 0x80u},
    {SNAP_COPY, 0x005531a0u, 0x006fecc0u, 0x100u},
    {SNAP_COPY, 0x00550200u, 0x006ff390u, 0x100u},
    {SNAP_COPY, 0x00550488u, 0x006808b8u, 0x8u},
    {SNAP_WORD, 0x00553188u, 0x006a3f78u, 4},
    {SNAP_WORD, 0x0054e7d0u, 0x00695f18u, 4},
    {SNAP_WORD, 0x0054e788u, 0x006ff680u, 4},
    {SNAP_COPY, 0x005558d8u, 0x006b2d40u, 0x1cu},
};

static const SnapStep POP_MAGIC[] = {
    {SNAP_COPY, 0x006a5f30u, 0x00633440u, 0xb640u},
    {SNAP_MASTER_RECORD_BACK, 0, 0x0063ea80u, 0x340u},   /* and back */
    {SNAP_COPY, 0x0069e730u, 0x0054d648u, 0xfa0u},
    {SNAP_COPY, 0x006ff710u, 0x005504d8u, 0xfa0u},
    {SNAP_COPY, 0x006b1590u, 0x00555988u, 0xfa0u},
    {SNAP_COPY, 0x0063edd0u, 0x00555940u, 0x40u},
    {SNAP_COPY, 0x0063ee90u, 0x00550498u, 0x40u},
    {SNAP_COPY, 0x0063ee30u, 0x00550408u, 0x40u},
    {SNAP_COPY, 0x00627870u, 0x0054e5f0u, 0x198u},
    {SNAP_COPY, 0x006a4a00u, 0x0054be48u, 0x8u},
    {SNAP_COPY, 0x00696870u, 0x00550448u, 0x8u},
    {SNAP_COPY, 0x006a2828u, 0x00550470u, 0x8u},
    {SNAP_COPY, 0x00695e00u, 0x00550478u, 0x8u},
    {SNAP_COPY, 0x006b3000u, 0x005528d0u, 0x60u},
    {SNAP_COPY, 0x006b2d90u, 0x00551478u, 0x80u},
    {SNAP_COPY, 0x007006e0u, 0x00555108u, 0x7d0u},
    {SNAP_COPY, 0x006a5750u, 0x0054be50u, 0x7d0u},
    {SNAP_WORD, 0x006a4a08u, 0x00550300u, 4},
    {SNAP_WORD, 0x006ff558u, 0x00554040u, 4},
    {SNAP_WORD, 0x0068a708u, 0x00550484u, 4},
    {SNAP_WORD, 0x006a5f20u, 0x00550490u, 4},
    {SNAP_WORD, 0x006a49fcu, 0x00552930u, 4},
    {SNAP_COPY, 0x006ff4d0u, 0x0054d5c0u, 0x80u},
    {SNAP_COPY, 0x006fecc0u, 0x005531a0u, 0x100u},
    {SNAP_COPY, 0x006ff390u, 0x00550200u, 0x100u},
    {SNAP_COPY, 0x006808b8u, 0x00550488u, 0x8u},
    {SNAP_WORD, 0x006a3f78u, 0x00553188u, 4},
    {SNAP_WORD, 0x00695f18u, 0x0054e7d0u, 4},
    {SNAP_WORD, 0x006ff680u, 0x0054e788u, 4},
    {SNAP_COPY, 0x006b2d40u, 0x005558d8u, 0x1cu},
};


typedef struct {
    const SnapStep *steps;
    int count;
    uint32_t instructions; /* the original's own instructions on its one path (the calls it makes are counted by their callees) */
} Snapshot;

#define SNAPSHOT(name, program, n) {name##_##program, (int)(sizeof(name##_##program) / sizeof(name##_##program[0])), n}

static const Snapshot SNAPSHOTS_DUEL[4] = {SNAPSHOT(SAVE, DUEL, 158), SNAPSHOT(RESTORE, DUEL, 152), SNAPSHOT(PUSH, DUEL, 141),
                                            SNAPSHOT(POP, DUEL, 141)};
/* MAGIC.EXE calls the runtime DLL's memcpy through a thunk, whose cost is not modelled, so the counts here are those of the same
 * code in DUEL.EXE: right for what this function runs itself, not for the copies. */
static const Snapshot SNAPSHOTS_MAGIC[4] = {SNAPSHOT(SAVE, MAGIC, 158), SNAPSHOT(RESTORE, MAGIC, 152), SNAPSHOT(PUSH, MAGIC, 141),
                                             SNAPSHOT(POP, MAGIC, 141)};

enum { SNAP_SAVE, SNAP_RESTORE, SNAP_PUSH, SNAP_POP };

static void snap_copy(Vm *vm, uint32_t dst, uint32_t src, uint32_t size)
{
    if (vm->L->entry[FN_CRT_MEMCPY])
        Native_Crt_Memcpy(vm, dst, src, size);
    else
        mem_copy(vm->mem, dst, src, size);
}

static void run_snapshot(Vm *vm, int which)
{
    const Snapshot *s = &(vm->L->program[0] == 'D' ? SNAPSHOTS_DUEL : SNAPSHOTS_MAGIC)[which];
    uint32_t master = vm->L->master_base - 0x10u; /* the table's record at index master_count is the one these copy */
    int i;

    native_cost_extra += s->instructions;
    for (i = 0; i < s->count; i++) {
        const SnapStep *st = &s->steps[i];
        switch (st->kind) {
        case SNAP_COPY:
            snap_copy(vm, st->dst, st->src, st->size);
            break;
        case SNAP_MASTER_RECORD:
            snap_copy(vm, st->dst, master + mem_rd32(vm->mem, vm->L->master_count) * MASTER_STRIDE, st->size);
            break;
        case SNAP_MASTER_RECORD_BACK:
            snap_copy(vm, master + mem_rd32(vm->mem, vm->L->master_count) * MASTER_STRIDE, st->src, st->size);
            break;
        case SNAP_WORD:
            mem_wr32(vm->mem, st->dst, mem_rd32(vm->mem, st->src));
            break;
        case SNAP_STORE:
            mem_wr32(vm->mem, st->dst, st->src);
            break;
        case SNAP_ASSERT_NONNEG:
            if ((int32_t)mem_rd32(vm->mem, st->dst) < 0)
                NATIVE_UNIMPLEMENTED("the spell stack count is negative (an assert in sid\\Ai.c)");
            break;
        case SNAP_CALL:
            if (st->dst == vm->L->entry[FN_AI_RESET_RANDOM_CURSOR])
                Native_Ai_ResetRandomCursor(vm);
            else
                vm_call(vm, CALLEE_AI_PREROLL_RANDOM, 0, NULL);
            break;
        }
    }
}

void Native_Ai_SaveGameState(Vm *vm)
{
    NATIVE_ENTER(FN_AI_SAVE_GAME_STATE);
    run_snapshot(vm, SNAP_SAVE);
}

void Native_Ai_RestoreGameState(Vm *vm)
{
    NATIVE_ENTER(FN_AI_RESTORE_GAME_STATE);
    run_snapshot(vm, SNAP_RESTORE);
}

void Native_Ai_PushBoardState(Vm *vm)
{
    NATIVE_ENTER(FN_AI_PUSH_BOARD_STATE);
    run_snapshot(vm, SNAP_PUSH);
}

void Native_Ai_PopBoardState(Vm *vm)
{
    NATIVE_ENTER(FN_AI_POP_BOARD_STATE);
    run_snapshot(vm, SNAP_POP);
}

/* The AI draws its random numbers from a table of 100 rolled at the start of a search; this is the cursor into it. */
void Native_Ai_ResetRandomCursor(Vm *vm)
{
    NATIVE_ENTER(FN_AI_RESET_RANDOM_CURSOR);
    native_cost_extra += 11;
    mem_wr32(vm->mem, vm->L->ai_random_cursor, 0);
}

/* Start of a trial: clear the trial list, put the game back, and outside the search forget the stage. 1558 instructions with the
 * search running, 1559 without (the same path plus the last store); the 256-entry loop is most of it. */
void Native_Ai_BeginTrial(Vm *vm)
{
    const Layout *L = vm->L;
    int i;

    NATIVE_ENTER(FN_AI_BEGIN_TRIAL);
    mem_wr32(vm->mem, L->ai_trial_word_a, 0);
    mem_wr32(vm->mem, L->ai_cursor, mem_rd32(vm->mem, L->ai_trial_word_a));
    mem_wr32(vm->mem, L->ai_trial_word_b, 0xffffffffu);
    for (i = 0; i < 0x100; i++)
        mem_wr32(vm->mem, L->ai_trial_choice + 4u * (uint32_t)i, 99);
    native_cost_extra += 1558;
    Native_Ai_RestoreGameState(vm);
    if (mem_rd32(vm->mem, L->is_ai_thinking) != 1) {
        mem_wr32(vm->mem, L->ai_search_stage, 0xffffffffu);
        native_cost_extra += 1;
    }
}
