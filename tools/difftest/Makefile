# Build the difftest harness: the native functions in src/native/ plus harness.c.
#   make -C tools/difftest            -> tools/difftest/build/harness
#   make -C tools/difftest asan       -> the same with address and undefined-behaviour sanitizers
CC ?= cc
CFLAGS ?= -std=c99 -O1 -g
WARN = -Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wno-sign-conversion
NATIVE = ../../src/native
SRCS = harness.c $(NATIVE)/mem.c $(NATIVE)/engine.c $(NATIVE)/layout.c $(NATIVE)/spell_stack.c \
       $(NATIVE)/card_query.c $(NATIVE)/event_context.c $(NATIVE)/card_util.c $(NATIVE)/ai_plan.c $(NATIVE)/card_scan.c $(NATIVE)/crt.c $(NATIVE)/ai_state.c $(NATIVE)/ai_eval.c
HDRS = $(NATIVE)/mem.h $(NATIVE)/engine.h

build/harness: $(SRCS) $(HDRS) | build
	$(CC) $(CFLAGS) $(WARN) -o $@ $(SRCS)

asan: $(SRCS) $(HDRS) | build
	$(CC) $(CFLAGS) $(WARN) -fsanitize=address,undefined -fno-omit-frame-pointer -o build/harness-asan $(SRCS)

build:
	mkdir -p build

clean:
	rm -rf build

# The harness for lifted code (tools/lift): GEN holds the handlers_gen.c that tools/lift/gen_handlers.py wrote.
GEN ?= ../../sources/generated/lift
flat: harness_flat.c $(GEN)/handlers_gen.c $(NATIVE)/lift_rt.h $(NATIVE)/lift_tables.h | build
	$(CC) $(CFLAGS) -Wall -Wno-unused-label -Wno-unused-variable -Wno-unused-but-set-variable -DLIFT_TRACK_WRITES -I$(NATIVE) -I$(GEN) \
	    -o build/harness-flat harness_flat.c $(GEN)/handlers_gen.c -lm

# The native layer with the lifted handlers linked in: the harness above plus lift_bridge.c and the generated code, with
# `Handler_<address>` functions running lifted, on the sparse memory image the native functions use.
BUILD ?= build
lifted: $(GEN)/handlers_gen.c $(SRCS) $(HDRS) $(NATIVE)/lift_bridge.c $(NATIVE)/lift_bridge.h $(NATIVE)/lift_rt.h
	mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -w -DLIFT_BACKEND_MEM -DLIFT_COUNT -I$(NATIVE) -I$(GEN) -c $(GEN)/handlers_gen.c -o $(BUILD)/handlers_gen.o
	$(CC) $(CFLAGS) $(WARN) -DNATIVE_LIFTED -I$(NATIVE) -o $(BUILD)/harness-lifted $(SRCS) $(NATIVE)/lift_bridge.c $(BUILD)/handlers_gen.o -lm

# The same with instruction coverage of the lifted code (FLAT_COV=file, then tools/lift/coverage.py).
lifted-cov: $(GEN)/handlers_gen.c $(SRCS) $(HDRS) $(NATIVE)/lift_bridge.c $(NATIVE)/lift_bridge.h $(NATIVE)/lift_rt.h
	mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -w -DLIFT_BACKEND_MEM -DLIFT_COVERAGE -I$(NATIVE) -I$(GEN) -c $(GEN)/handlers_gen.c -o $(BUILD)/handlers_gen_cov.o
	$(CC) $(CFLAGS) $(WARN) -DNATIVE_LIFTED -DLIFT_COVERAGE -I$(NATIVE) -o $(BUILD)/harness-lifted-cov $(SRCS) $(NATIVE)/lift_bridge.c $(BUILD)/handlers_gen_cov.o -lm

# The native layer as a shared library for the emulator to host (tools/emu_spike/winemu/native_host.py). With the generated
# handlers when GEN has them, without otherwise.
HOSTSRCS = $(NATIVE)/mem.c $(NATIVE)/engine.c $(NATIVE)/layout.c $(NATIVE)/spell_stack.c $(NATIVE)/card_query.c \
           $(NATIVE)/event_context.c $(NATIVE)/card_util.c $(NATIVE)/ai_plan.c $(NATIVE)/card_scan.c $(NATIVE)/crt.c $(NATIVE)/ai_state.c $(NATIVE)/ai_eval.c $(NATIVE)/native_host.c
host: $(HOSTSRCS) | build
	mkdir -p $(BUILD)
	if [ -f $(GEN)/handlers_gen.c ]; then \
	  $(CC) $(CFLAGS) -w -fPIC -DLIFT_BACKEND_MEM -DLIFT_COUNT -I$(NATIVE) -I$(GEN) -c $(GEN)/handlers_gen.c -o $(BUILD)/handlers_host.o && \
	  $(CC) $(CFLAGS) $(WARN) -fPIC -shared -DHOST_LIFTED -I$(NATIVE) -o $(BUILD)/libnative_host.dylib $(HOSTSRCS) \
	    $(NATIVE)/lift_bridge.c $(BUILD)/handlers_host.o; \
	else \
	  $(CC) $(CFLAGS) $(WARN) -fPIC -shared -I$(NATIVE) -o $(BUILD)/libnative_host.dylib $(HOSTSRCS); \
	fi

.PHONY: asan clean flat lifted lifted-cov host
