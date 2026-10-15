/* test_stubs.c - what the tests do not link: the tables a generated program defines (none here), the loader's import lookup, the main image. */
#include "port.h"

#ifndef TEST_REAL_MODULE
/* the tables a generated program defines: none here (test_module.c is built with TEST_REAL_MODULE and loads a game module instead, through gamemod.c) */
static const LiftedFn no_lifted[] = {{0, 0, 0}};
static const CalleeRow no_functions[] = {{0, 0, 0}};
static const LiftImportSig no_sigs[] = {{0, 0, 0, 0}};
static const LiftModule *const no_modules[] = {0};
static const LiftGame test_game = {LIFT_ABI, sizeof(LiftGame), "TEST", no_lifted, 0, no_functions, 0, no_sigs, 0, no_modules};
const LiftGame *lift_game = &test_game;
#endif

Image main_image;
Import *import_by_slot_or_stub(uint32_t addr) { (void)addr; return NULL; }
void imports_report(void) {}
int pe_load_module(const char *path, uint32_t base, Image *img) { (void)path; (void)base; (void)img; return -1; }
uint32_t pe_export(uint32_t hmod, const char *name) { (void)hmod; (void)name; return 0; }
