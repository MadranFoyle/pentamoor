# The program is two parts. The runtime, `pentamoor-run`, is everything except the lifted code: the PE loader, scheduler, Win32 layer, SDL front end, sound. It holds no game-derived
# code, builds without any generated source, and is the same for every game program. The game module is a library made only from the lifted C that tools/lift writes into
# sources/generated/lift_<program>/ (MAGIC and its DLLs: lift_magic_all; DECK.EXE: lift_deck; DUEL.EXE: lift_duel). The runtime loads it by path at start and talks to it through
# two tables only (src/native/lift_rt.h LiftHost, lift_tables.h LiftGame; src/port/gamemod.c), never by symbol name.
#
#   make -C src/port                     the runtime, and a module for each program whose generated C is there       (build/pentamoor-run, build/game_magic.so ...)
#
# Windows: the same Makefile, in an MSYS2 MINGW64 shell (pacman -S make mingw-w64-x86_64-gcc mingw-w64-x86_64-SDL2): the runtime is build/pentamoor-run.exe and a module
# build/game_magic.dll. From another host, `make WINDOWS=1 CC=x86_64-w64-mingw32-gcc SDL_CFLAGS=-I<SDL2's include/SDL2> SDL_LIBS=-L<its lib> -lSDL2` cross-compiles.
# The host-specific code is in plat.h, plat_posix.c and plat_win.c (docs/PHASE_C.md, "Windows").
#   make -C src/port runtime             the runtime only (needs no game files)
#   make -C src/port modules            the game modules only (needs no runtime: a prebuilt runtime can be used with them)
#   make -C src/port module-magic        one module (module-deck, module-duel)
#   build/pentamoor-run -m build/game_magic.so sources/installed/Magic/Program/MAGIC.EXE     (what ./pentamoor does)
#   make -C src/port static GEN=../../sources/generated/lift_magic_all BUILD=build_static    the old single executable, lifted code linked in (build_static/pentamoor)
BUILD ?= build
CC ?= cc
CFLAGS ?= -std=gnu99 -O1 -g -Wall -Wextra -Wshadow -Wno-unused-parameter
UNAME := $(shell uname -s)
# Windows: an MSYS2 / MinGW shell (OS is Windows_NT there, uname says MINGW64_NT-...), or WINDOWS=1 for a cross compiler.
ifneq ($(filter MINGW% MSYS% CYGWIN%,$(UNAME))$(filter Windows_NT,$(OS)),)
WINDOWS = 1
endif
ifdef WINDOWS
SOEXT = dll
# -static-libgcc: the module needs no libgcc_s DLL beside it.
SOFLAGS = -shared -static-libgcc
else ifeq ($(UNAME),Darwin)
SOEXT = dylib
SOFLAGS = -dynamiclib
else
SOEXT = so
SOFLAGS = -shared
endif
ifdef WINDOWS
EXE = .exe
# The unit tests and the runtime link the C library's pthreads (winpthreads) statically, so a release needs no libwinpthread-1.dll or libgcc DLL beside it (SDL2.dll is the
# one it does need). The whole archive: winpthreads' thread-exit hook (thread-local data, key destructors) lives in an object nothing refers to by name.
# __USE_MINGW_ANSI_STDIO: printf's %zu and %llu work on the older msvcrt runtime too. -lwinmm: timeBeginPeriod (plat_win.c). The 8 MB stack is for every thread (lifted code
# runs on the C stack). SDL_MAIN_HANDLED: SDL does not rename main.
PTHREAD_LIBS = -static-libgcc -Wl,-Bstatic,--whole-archive -lwinpthread -Wl,--no-whole-archive,-Bdynamic
WINFLAGS = -D__USE_MINGW_ANSI_STDIO=1 -DSDL_MAIN_HANDLED
WINLIBS = -lwinmm -Wl,--stack,8388608
else
EXE =
PTHREAD_LIBS = -lpthread
WINFLAGS =
WINLIBS =
endif
# The window: SDL2 if sdl2-config is there (PORT_HEADLESS=1 runs without it), else none. On Windows sdl2-config also asks for SDL2main, -mwindows (no console: the log would
# go nowhere) and -Dmain=SDL_main (a WinMain that calls SDL_main): none of them, the runtime has its own main and runs in the console.
ifeq ($(origin SDL_CFLAGS),undefined)
SDL_CFLAGS := $(filter-out -Dmain=SDL_main,$(shell sdl2-config --cflags 2>/dev/null))
endif
ifeq ($(origin SDL_LIBS),undefined)
SDL_LIBS := $(filter-out -lmingw32 -lSDL2main -mwindows,$(shell sdl2-config --libs 2>/dev/null))
endif
ifneq ($(SDL_CFLAGS),)
FRONT = front.c front_sdl.c
else
FRONT = front.c front_none.c
endif
# dlopen is in libc on macOS and current glibc; older glibc wants -ldl. Windows: LoadLibrary (plat_win.c), nothing to link.
DL_LIBS = $(if $(filter Linux,$(UNAME)),-ldl,)
PLAT = plat_posix.c plat_win.c
SRC = main.c $(PLAT) guest.c pe.c call.c sched.c kernel32.c kernel32_rt.c crt.c stdio.c cformat.c paths.c user32.c controls.c input.c filedlg.c winhelp.c msgbox.c menus.c gdi.c gdi_blit.c gdi_text.c font.c ui.c compose.c lzw.c modules.c sound.c video.c movie.c pace.c gamemod.c pad.c nav.c navwm.c screens.c steamdeck.c textin.c textfocus.c yesno.c profile.c $(FRONT)
HEADERS = plat.h port.h profile.h wm.h gdi.h gdi_int.h sched.h front.h pad.h nav.h navwm.h screens.h steamdeck.h textin.h yesno.h filedlg.h winhelp.h msgbox.h ../native/lift_rt.h ../native/lift_tables.h
RTFLAGS = -DLIFT_BACKEND_FLAT4G -DLIFT_PREEMPT $(WINFLAGS) -iquote . -I../native

PROGRAMS = magic deck duel
GEN_magic ?= ../../sources/generated/lift_magic_all
GEN_deck ?= ../../sources/generated/lift_deck
GEN_duel ?= ../../sources/generated/lift_duel
# The programs that have generated C to build a module from.
AVAILABLE = $(foreach p,$(PROGRAMS),$(if $(wildcard $(GEN_$(p))/handlers_gen.c),$(p)))

# `make GEN=... BUILD=...` as it was before the split (the old documents use it) still makes the single executable.
ifeq ($(origin GEN),command line)
.DEFAULT_GOAL := static
endif
all: runtime modules
modules: $(foreach p,$(AVAILABLE),module-$(p))
runtime: $(BUILD)/pentamoor-run$(EXE)
.PHONY: all runtime modules $(foreach p,$(PROGRAMS),module-$(p)) static

$(BUILD)/pentamoor-run$(EXE): $(SRC) $(HEADERS)
	mkdir -p $(BUILD)
	$(CC) $(CFLAGS) $(EXTRA) $(RTFLAGS) $(SDL_CFLAGS) -o $@ $(SRC) $(SDL_LIBS) $(PTHREAD_LIBS) -lm $(DL_LIBS) $(WINLIBS)

# A game module: every generated *_gen.c of the program (the executable's handlers, the DLLs, the module list) compiled apart, plus modglue.c, linked as a library that exports
# pentamoor_game_init and nothing else. Plain C99; -fPIC, hidden symbols (the lifted code reaches the runtime through the LiftHost it is given, so it needs none of its symbols).
# The lifted code is large (36 MB of C): each file is compiled apart, and only when it changes. Windows: no -fPIC (every PE image is relocatable; gcc would only warn) and
# no visibility flag (a symbol is exported only if modglue.c says dllexport, which pentamoor_game_init does).
ifdef WINDOWS
MODFLAGS = -std=gnu99 -O1 -w $(EXTRA) -DLIFT_BACKEND_FLAT4G -DLIFT_PREEMPT -DLIFT_MODULE -I../native
else
MODFLAGS = -std=gnu99 -O1 -w $(EXTRA) -fPIC -fvisibility=hidden -DLIFT_BACKEND_FLAT4G -DLIFT_PREEMPT -DLIFT_MODULE -I../native
endif
define MODULE_RULES
GENSRC_$(1) = $$(wildcard $$(GEN_$(1))/*_gen.c)
MODOBJS_$(1) = $$(patsubst $$(GEN_$(1))/%.c,$$(BUILD)/$(1)/%.o,$$(GENSRC_$(1))) $$(BUILD)/$(1)/modglue.o $$(if $$(wildcard $$(GEN_$(1))/modules_gen.c),,$$(BUILD)/$(1)/modules_none.o)
module-$(1): $$(BUILD)/game_$(1).$(SOEXT)
$$(BUILD)/game_$(1).$(SOEXT): $$(MODOBJS_$(1))
	$$(CC) $$(SOFLAGS) -o $$@ $$(MODOBJS_$(1)) -lm
$$(BUILD)/$(1)/%.o: $$(GEN_$(1))/%.c ../native/lift_rt.h ../native/lift_tables.h
	mkdir -p $$(BUILD)/$(1)
	$$(CC) $$(MODFLAGS) -c -o $$@ $$<
$$(BUILD)/$(1)/%.o: %.c ../native/lift_rt.h ../native/lift_tables.h
	mkdir -p $$(BUILD)/$(1)
	$$(CC) $$(MODFLAGS) -c -o $$@ $$<
endef
GEN_stub = stubgame
$(foreach p,$(PROGRAMS) stub,$(eval $(call MODULE_RULES,$(p))))

# The old single executable: the same code, with the module linked in (GEN: one program's generated directory; BUILD: where its objects go).
GEN ?= $(GEN_magic)
STATIC_SRCS = $(wildcard $(GEN)/*_gen.c)
STATIC_OBJS = $(patsubst $(GEN)/%.c,$(BUILD)/%.o,$(STATIC_SRCS)) $(BUILD)/modglue.o $(if $(wildcard $(GEN)/modules_gen.c),,$(BUILD)/modules_none.o)
static: $(BUILD)/pentamoor
$(BUILD)/pentamoor: $(SRC) $(HEADERS) $(STATIC_OBJS)
	$(CC) $(CFLAGS) $(EXTRA) $(RTFLAGS) -DPENTAMOOR_STATIC_GAME $(SDL_CFLAGS) -o $@ $(SRC) $(STATIC_OBJS) $(SDL_LIBS) $(PTHREAD_LIBS) -lm $(WINLIBS)
$(BUILD)/%.o: $(GEN)/%.c ../native/lift_rt.h ../native/lift_tables.h
	mkdir -p $(BUILD)
	$(CC) -std=gnu99 -O1 -w $(EXTRA) -DLIFT_BACKEND_FLAT4G -DLIFT_PREEMPT -DLIFT_MODULE -I../native -c -o $@ $<
$(BUILD)/modglue.o $(BUILD)/modules_none.o: $(BUILD)/%.o: %.c ../native/lift_rt.h ../native/lift_tables.h
	mkdir -p $(BUILD)
	$(CC) -std=gnu99 -O1 -w $(EXTRA) -DLIFT_BACKEND_FLAT4G -DLIFT_PREEMPT -DLIFT_MODULE -I../native -c -o $@ $<

clean:
	rm -rf $(BUILD)

# The tests of the window manager and the graphics layer: host functions stand in for the game's window procedures, so no game files are needed.
LIB_SRC = $(PLAT) nav.c navwm.c screens.c lzw.c guest.c call.c sched.c kernel32.c kernel32_rt.c crt.c stdio.c cformat.c paths.c user32.c controls.c input.c filedlg.c winhelp.c msgbox.c menus.c gdi.c gdi_blit.c gdi_text.c font.c ui.c compose.c front.c yesno.c pace.c textfocus.c profile.c steamdeck.c modules.c sound.c video.c movie.c
TEST_DEPS = test_stubs.c $(LIB_SRC) nav.h navwm.h screens.h port.h wm.h gdi.h gdi_int.h sched.h front.h filedlg.h winhelp.h msgbox.h yesno.h profile.h

$(BUILD)/test_wm$(EXE): test_wm.c $(TEST_DEPS)
	mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -DLIFT_BACKEND_FLAT4G -DLIFT_PREEMPT $(WINFLAGS) -iquote . -I../native -o $@ test_wm.c test_stubs.c $(LIB_SRC) $(PTHREAD_LIBS) -lm $(WINLIBS)

$(BUILD)/test_gdi$(EXE): test_gdi.c $(TEST_DEPS)
	mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -DLIFT_BACKEND_FLAT4G -DLIFT_PREEMPT $(WINFLAGS) -iquote . -I../native -o $@ test_gdi.c test_stubs.c $(LIB_SRC) $(PTHREAD_LIBS) -lm $(WINLIBS)

$(BUILD)/test_sound$(EXE): test_sound.c $(TEST_DEPS)
	mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -DLIFT_BACKEND_FLAT4G -DLIFT_PREEMPT $(WINFLAGS) -iquote . -I../native -o $@ test_sound.c test_stubs.c $(LIB_SRC) $(PTHREAD_LIBS) -lm $(WINLIBS)

$(BUILD)/test_movie$(EXE): test_movie.c $(TEST_DEPS) movie.h
	mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -DLIFT_BACKEND_FLAT4G -DLIFT_PREEMPT $(WINFLAGS) -iquote . -I../native -o $@ test_movie.c test_stubs.c $(LIB_SRC) $(PTHREAD_LIBS) -lm $(WINLIBS)

# The runtime loads the stub game module and runs lifted-style functions in it (needs the module built: `test` does that first).
$(BUILD)/test_module$(EXE): test_module.c gamemod.c $(TEST_DEPS)
	mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -DLIFT_BACKEND_FLAT4G -DLIFT_PREEMPT -DTEST_REAL_MODULE $(WINFLAGS) -iquote . -I../native -o $@ test_module.c gamemod.c test_stubs.c $(LIB_SRC) $(PTHREAD_LIBS) -lm $(WINLIBS) $(DL_LIBS)

# The controller logic: pure, no SDL and no game (pad.c).
$(BUILD)/test_pad$(EXE): test_pad.c pad.c pad.h
	mkdir -p $(BUILD)
	$(CC) $(CFLAGS) $(WINFLAGS) -iquote . -o $@ test_pad.c pad.c -lm $(WINLIBS)

# The spatial navigation: pure too (nav.c).
$(BUILD)/test_nav$(EXE): test_nav.c nav.c nav.h
	mkdir -p $(BUILD)
	$(CC) $(CFLAGS) $(WINFLAGS) -iquote . -o $@ test_nav.c nav.c $(WINLIBS)

# The Steam Deck decisions and typed text with no key: pure (steamdeck.c, textin.c).
$(BUILD)/test_steamdeck$(EXE): test_steamdeck.c steamdeck.c steamdeck.h textin.c textin.h
	mkdir -p $(BUILD)
	$(CC) $(CFLAGS) $(WINFLAGS) -iquote . -o $@ test_steamdeck.c steamdeck.c textin.c $(WINLIBS)

# Build profiles (profile.c): the table of known builds and their addresses, the build id, the choice of the profile, the hooks an unknown build gets (none).
$(BUILD)/test_profile$(EXE): test_profile.c $(TEST_DEPS)
	mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -DLIFT_BACKEND_FLAT4G -DLIFT_PREEMPT $(WINFLAGS) -iquote . -I../native -o $@ test_profile.c test_stubs.c $(LIB_SRC) $(PTHREAD_LIBS) -lm $(WINLIBS)

$(BUILD)/test_paths$(EXE): test_paths.c $(TEST_DEPS)
	mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -DLIFT_BACKEND_FLAT4G -DLIFT_PREEMPT $(WINFLAGS) -iquote . -I../native -o $@ test_paths.c test_stubs.c $(LIB_SRC) $(PTHREAD_LIBS) -lm $(WINLIBS)

# The SDL front end compiled (not linked) with its warnings on: needs only SDL2's headers, no game files. CI runs it.
check-front:
	@test -n "$(SDL_CFLAGS)" || { echo "check-front: sdl2-config not found"; exit 1; }
	$(CC) $(CFLAGS) -DLIFT_BACKEND_FLAT4G -DLIFT_PREEMPT $(WINFLAGS) -iquote . -I../native $(SDL_CFLAGS) -fsyntax-only front_sdl.c

.PHONY: clean test check-front check-module check-run check-program check-build

# The loading path without any game: a module with no functions (stubgame/) is built and loaded by the runtime, which then stops because the program it was given is not there.
# A missing module and a module that is not one are refused with their own messages. CI runs it. (The program path is relative: MSYS rewrites an argument that starts with / when it starts a Windows program.)
check-module: runtime module-stub
	@out=$$(PORT_HEADLESS=1 $(BUILD)/pentamoor-run$(EXE) -m $(BUILD)/game_stub.$(SOEXT) no-such-folder/Program/MAGIC.EXE 2>&1); \
	  echo "$$out" | grep -q "cannot open no-such-folder/Program/MAGIC.EXE" || { echo "check-module: the stub module did not load: $$out"; exit 1; }
	@out=$$(PORT_HEADLESS=1 $(BUILD)/pentamoor-run$(EXE) -m $(BUILD)/nonexistent.$(SOEXT) x.exe 2>&1); \
	  echo "$$out" | grep -q "cannot load the game module" || { echo "check-module: a missing module was not refused: $$out"; exit 1; }
	@out=$$(PORT_HEADLESS=1 $(BUILD)/pentamoor-run$(EXE) -m $(BUILD)/pentamoor-run$(EXE) x.exe 2>&1); \
	  echo "$$out" | grep -q "no pentamoor_game_init\|cannot load the game module" || { echo "check-module: a non-module was not refused: $$out"; exit 1; }
	@echo "check-module: ok"

# A program through the whole loading path with no game file: stubgame/mkpe.c writes a tiny PE (stub.exe: an import table and one byte of code), the runtime maps it, resolves its imports,
# and runs the stub module's lifted function at its entry point, which creates HELLO.TXT in the overlay through kernel32 (CreateFileA, WriteFile, CloseHandle) and ends with
# ExitProcess(7). Checks the exit status, that the overlay was made, and that the file holds exactly 24 bytes (a text-mode write would make 25). CI runs it.
$(BUILD)/mkpe$(EXE): stubgame/mkpe.c
	mkdir -p $(BUILD)
	$(CC) -O1 -o $@ $<

$(BUILD)/stub.exe: $(BUILD)/mkpe$(EXE)
	$(BUILD)/mkpe$(EXE) $@

check-program: runtime module-stub $(BUILD)/stub.exe
	rm -rf $(BUILD)/prog_overlay $(BUILD)/prog_game
	mkdir -p $(BUILD)/prog_game
	@PORT_UNKNOWN_BUILD=1 PORT_HEADLESS=1 PORT_OVERLAY=$(BUILD)/prog_overlay $(BUILD)/pentamoor-run$(EXE) -m $(BUILD)/game_stub.$(SOEXT) $(BUILD)/stub.exe $(BUILD)/prog_game > $(BUILD)/prog.log 2>&1; status=$$?; \
	  [ $$status -eq 7 ] || { echo "check-program: exit status $$status, not 7"; cat $(BUILD)/prog.log; exit 1; }
	@[ "`wc -c < $(BUILD)/prog_overlay/HELLO.TXT`" -eq 24 ] && grep -q "hello from lifted code" $(BUILD)/prog_overlay/HELLO.TXT || { echo "check-program: HELLO.TXT is not what the program wrote"; cat $(BUILD)/prog.log; exit 1; }
	@grep -q "PORT_UNKNOWN_BUILD=1 is set" $(BUILD)/prog.log || { echo "check-program: no warning about the unknown build"; cat $(BUILD)/prog.log; exit 1; }
	@echo "check-program: ok"

# An unsupported build is refused: the same program and module as check-program, but a build no profile has (stub.exe is not a build of the game), without PORT_UNKNOWN_BUILD:
# exit status 3, the message names the file, the build id and what is supported, and the program has not run (no HELLO.TXT). A program that is not the one the module was lifted from
# is refused too (the module's build id is stub.exe's). CI runs it.
check-build: runtime module-stub $(BUILD)/stub.exe
	rm -rf $(BUILD)/build_overlay $(BUILD)/prog_game
	mkdir -p $(BUILD)/prog_game
	cp $(BUILD)/stub.exe $(BUILD)/other.exe
	printf 'x' >> $(BUILD)/other.exe
	@PORT_HEADLESS=1 PORT_OVERLAY=$(BUILD)/build_overlay $(BUILD)/pentamoor-run$(EXE) -m $(BUILD)/game_stub.$(SOEXT) $(BUILD)/stub.exe $(BUILD)/prog_game > $(BUILD)/build.log 2>&1; status=$$?; \
	  [ $$status -eq 3 ] || { echo "check-build: exit status $$status, not 3"; cat $(BUILD)/build.log; exit 1; }
	@grep -q "pentamoor: stub.exe is build a619942cb4f2a8284c233ba23f401a2fb0302dcfc84e469462a6be84ba871382, which this version does not support (supported: " $(BUILD)/build.log || { echo "check-build: no message about the unsupported build"; cat $(BUILD)/build.log; exit 1; }
	@[ ! -e $(BUILD)/build_overlay/HELLO.TXT ] || { echo "check-build: the unsupported program ran"; exit 1; }
	@PORT_HEADLESS=1 PORT_OVERLAY=$(BUILD)/build_overlay $(BUILD)/pentamoor-run$(EXE) -m $(BUILD)/game_stub.$(SOEXT) $(BUILD)/other.exe $(BUILD)/prog_game > $(BUILD)/build.log 2>&1; status=$$?; \
	  [ $$status -eq 3 ] || { echo "check-build: another file: exit status $$status, not 3"; cat $(BUILD)/build.log; exit 1; }
	@grep -q "but the game module was made from build a619942c" $(BUILD)/build.log || { echo "check-build: no message about the file that is not the module's"; cat $(BUILD)/build.log; exit 1; }
	@echo "check-build: ok"

# The window half of the front end started for real, on SDL's dummy drivers (no display, no sound device): SDL is initialised, the window, the renderer and the audio device are
# made, the game runs on its thread (the window loop on this one), and the program, which is not there, ends it with an error. CI runs it.
check-run: runtime module-stub
	@out=$$(SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy $(BUILD)/pentamoor-run$(EXE) -m $(BUILD)/game_stub.$(SOEXT) no-such-folder/Program/MAGIC.EXE 2>&1); status=$$?; \
	  echo "$$out" | grep -q "cannot open no-such-folder/Program/MAGIC.EXE" && [ $$status -eq 2 ] || { echo "check-run: unexpected (exit $$status): $$out"; exit 1; }
	@echo "check-run: ok"


test: $(BUILD)/test_profile$(EXE) $(BUILD)/test_steamdeck$(EXE) $(BUILD)/test_wm$(EXE) $(BUILD)/test_gdi$(EXE) $(BUILD)/test_sound$(EXE) $(BUILD)/test_movie$(EXE) $(BUILD)/test_paths$(EXE) $(BUILD)/test_pad$(EXE) $(BUILD)/test_nav$(EXE) $(BUILD)/test_module$(EXE) module-stub
	$(BUILD)/test_profile$(EXE)
	$(BUILD)/test_wm$(EXE)
	$(BUILD)/test_pad$(EXE)
	$(BUILD)/test_nav$(EXE)
	$(BUILD)/test_steamdeck$(EXE)
	$(BUILD)/test_gdi$(EXE)
	$(BUILD)/test_sound$(EXE)
	$(BUILD)/test_movie$(EXE)
	$(BUILD)/test_paths$(EXE)
	$(BUILD)/test_module$(EXE) $(BUILD)/game_stub.$(SOEXT)
