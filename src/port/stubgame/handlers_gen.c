/* A game module with almost nothing in it. `make check-module` builds it and has the runtime load it, with no game file; `make test` (test_module.c) also runs three
 * of its functions, and `make check-program` runs the fourth as the entry point of a program the runtime loads (stub.exe, from mkpe.c). They are written the way tools/lift writes a function (the same macros of lift_rt.h: the registers as locals, the guest's memory through RD32/WR32, a call out
 * through lift_call, back-edges, the x87 stack, and a return through lift_ret_edx), so the C of a lifted function is compiled by the host's compiler and run through the
 * module's pointers into the runtime on every platform CI builds on, without the game. Not generated, and not the game's: the addresses are the test's own. */
#include "lift_rt.h"
#include "lift_tables.h"

#define STUB_MAIN 0x00401000u         /* the entry point of the PE that stubgame/mkpe.c writes (stub.exe): writes HELLO.TXT through kernel32, then ExitProcess(7) */
#define STUB_SUM 0x00710000u          /* uint32_t sum(const uint32_t *p, uint32_t n): the dwords of guest memory added up, a back-edge for each */
#define STUB_CALL 0x00710100u         /* uint32_t call(uint32_t fn, uint32_t a, uint32_t b): calls the host function fn(a, b), stores its result at 0x00720000, returns it + 1 */
#define STUB_X87 0x00710200u          /* void x87(double *p, uint32_t *q): p[1] = p[0] * 2 + 0.5 on the x87 stack, *q = 0xC0DE; EDX is 0x1234 on return */

uint32_t lifted_stub_sum(uint32_t esp)
{
    uint32_t R_eax = lift_in.eax, R_ecx = lift_in.ecx, R_edx = lift_in.edx, R_ebx = lift_in.ebx, R_esp = esp,
             R_ebp = lift_in.ebp, R_esi = lift_in.esi, R_edi = lift_in.edi;
    uint32_t ZF = 0, SF = 0, CF = 0, OF = 0;
L_00710000:; LIFT_COV(0x710000u);  /* mov esi, dword ptr [esp + 4] */
    R_esi = RD32((uint32_t)(R_esp + 0x4u));
L_00710004:; LIFT_COV(0x710004u);  /* mov ecx, dword ptr [esp + 8] */
    R_ecx = RD32((uint32_t)(R_esp + 0x8u));
L_00710008:; LIFT_COV(0x710008u);  /* xor eax, eax */
    { uint32_t a_ = R_eax, b_ = R_eax, r_;
    r_ = a_ ^ b_;
    FLAGS_LOGIC(r_, 32);
    R_eax = r_;
    }
L_0071000a:; LIFT_COV(0x71000au);  /* add eax, dword ptr [esi] */
    { uint32_t a_ = R_eax, b_ = RD32((uint32_t)(R_esi)), r_;
    r_ = a_ + b_;
    FLAGS_ADD(a_, b_, r_, 32);
    R_eax = r_;
    }
L_0071000c:; LIFT_COV(0x71000cu);  /* add esi, 4 */
    { uint32_t a_ = R_esi, b_ = 0x4u, r_;
    r_ = a_ + b_;
    FLAGS_ADD(a_, b_, r_, 32);
    R_esi = r_;
    }
L_0071000f:; LIFT_COV(0x71000fu);  /* dec ecx */
    { uint32_t a_ = R_ecx, r_ = a_ - 1u; FLAGS_ZS(r_, 32); OF = (a_ & MASK(32)) == (1u << (32 - 1));
    R_ecx = r_;
    }
L_00710010:; LIFT_COV(0x710010u);  /* jne 0x71000a */
    if (!ZF) { LIFT_BACKEDGE(); goto L_0071000a; }
L_00710012:; LIFT_COV(0x710012u);  /* ret  */
    LIFT_RET(0x710000u);
    lift_ret_edx = R_edx;
    return R_eax;
}

uint32_t lifted_stub_call(uint32_t esp)
{
    uint32_t R_eax = lift_in.eax, R_ecx = lift_in.ecx, R_edx = lift_in.edx, R_ebx = lift_in.ebx, R_esp = esp,
             R_ebp = lift_in.ebp, R_esi = lift_in.esi, R_edi = lift_in.edi;
    uint32_t ZF = 0, SF = 0, CF = 0, OF = 0;
L_00710100:; LIFT_COV(0x710100u);  /* mov esi, dword ptr [esp + 4] */
    R_esi = RD32((uint32_t)(R_esp + 0x4u));
L_00710104:; LIFT_COV(0x710104u);  /* mov ebx, dword ptr [esp + 8] */
    R_ebx = RD32((uint32_t)(R_esp + 0x8u));
L_00710108:; LIFT_COV(0x710108u);  /* mov edi, dword ptr [esp + 0xc] */
    R_edi = RD32((uint32_t)(R_esp + 0xcu));
L_0071010c:; LIFT_COV(0x71010cu);  /* push edi */
    { uint32_t t_ = R_edi; R_esp -= 4; WR32(R_esp, t_); }
L_0071010d:; LIFT_COV(0x71010du);  /* push ebx */
    { uint32_t t_ = R_ebx; R_esp -= 4; WR32(R_esp, t_); }
L_0071010e:; LIFT_COV(0x71010eu);  /* call esi */
    R_esp -= 4;
    WR32(R_esp, 0x710110u);
    LIFT_CALL_REGS();
    { uint32_t cl_ = 0; R_eax = lift_call(R_esi, R_esp + 4u, &cl_); R_esp += 4u + cl_; }
    R_ecx = 0xcdcdcdcdu; R_edx = lift_ret_edx;
L_00710110:; LIFT_COV(0x710110u);  /* add esp, 8 */
    { uint32_t a_ = R_esp, b_ = 0x8u, r_;
    r_ = a_ + b_;
    FLAGS_ADD(a_, b_, r_, 32);
    R_esp = r_;
    }
L_00710113:; LIFT_COV(0x710113u);  /* mov dword ptr [0x720000], eax */
    WR32((uint32_t)(0x720000u), R_eax);
L_00710118:; LIFT_COV(0x710118u);  /* inc eax */
    { uint32_t a_ = R_eax, r_ = a_ + 1u; FLAGS_ZS(r_, 32); OF = (a_ & MASK(32)) == (1u << (32 - 1)) - 1u;
    R_eax = r_;
    }
L_00710119:; LIFT_COV(0x710119u);  /* ret  */
    LIFT_RET(0x710100u);
    lift_ret_edx = R_edx;
    return R_eax;
}

uint32_t lifted_stub_x87(uint32_t esp)
{
    uint32_t R_eax = lift_in.eax, R_ecx = lift_in.ecx, R_edx = lift_in.edx, R_ebx = lift_in.ebx, R_esp = esp,
             R_ebp = lift_in.ebp, R_esi = lift_in.esi, R_edi = lift_in.edi;
    uint32_t ZF = 0, SF = 0, CF = 0, OF = 0;
L_00710200:; LIFT_COV(0x710200u);  /* mov esi, dword ptr [esp + 4] */
    R_esi = RD32((uint32_t)(R_esp + 0x4u));
L_00710204:; LIFT_COV(0x710204u);  /* mov edi, dword ptr [esp + 8] */
    R_edi = RD32((uint32_t)(R_esp + 0x8u));
L_00710208:; LIFT_COV(0x710208u);  /* fld qword ptr [esi] */
    X87_PUSH_BITS(RD64((uint32_t)(R_esi)));
L_0071020a:; LIFT_COV(0x71020au);  /* fadd st(0), st(0) */
    SET_ST(0, ST(0) + ST(0));
L_0071020c:; LIFT_COV(0x71020cu);  /* fadd dword ptr [0x710300] */
    SET_ST(0, ST(0) + x87_f32(0x3f000000u));
L_00710212:; LIFT_COV(0x710212u);  /* fstp qword ptr [esi + 8] */
    WR64((uint32_t)(R_esi + 0x8u), X87[XT]);
    X87_POP();
L_00710215:; LIFT_COV(0x710215u);  /* mov dword ptr [edi], 0xc0de */
    WR32((uint32_t)(R_edi), 0xc0deu);
L_0071021b:; LIFT_COV(0x71021bu);  /* mov edx, 0x1234 */
    R_edx = 0x1234u;
L_00710220:; LIFT_COV(0x710220u);  /* ret  */
    LIFT_RET(0x710200u);
    lift_ret_edx = R_edx;
    return R_eax;
}

/* The entry point of stub.exe, which `make check-program` runs: CreateFileA, WriteFile and CloseHandle on "HELLO.TXT" (the game folder's, so the overlay's), then ExitProcess(7).
 * The imports are called through their address-table slots as lifted code does (mkpe.c puts the table at 0x402100). Not in the lifter's style where it only sets up memory. */
static void stub_put(uint32_t a, const char *text)
{
    for (;; a++, text++) {
        WR8(a, *text);
        if (!*text)
            break;
    }
}

#define PUSH(v) do { uint32_t t_ = (v); R_esp -= 4; WR32(R_esp, t_); } while (0)
#define CALL_SLOT(slot, ret) do { R_esp -= 4; WR32(R_esp, (ret)); LIFT_CALL_REGS(); \
    { uint32_t cl_ = 0; R_eax = lift_call((slot), R_esp + 4u, &cl_); R_esp += 4u + cl_; } R_ecx = 0xcdcdcdcdu; R_edx = lift_ret_edx; } while (0)

uint32_t lifted_stub_main(uint32_t esp)
{
    uint32_t R_eax = lift_in.eax, R_ecx = lift_in.ecx, R_edx = lift_in.edx, R_ebx = lift_in.ebx, R_esp = esp,
             R_ebp = lift_in.ebp, R_esi = lift_in.esi, R_edi = lift_in.edi;
    uint32_t ZF = 0, SF = 0, CF = 0, OF = 0;
L_00401000:; LIFT_COV(0x401000u);
    stub_put(0x00500000u, "HELLO.TXT");
    stub_put(0x00500100u, "hello from lifted code\r\n");                  /* 24 bytes */
    PUSH(0); PUSH(0x80u); PUSH(2u); PUSH(0); PUSH(0); PUSH(0x40000000u); PUSH(0x00500000u);
    CALL_SLOT(0x402104u, 0x401010u);                                    /* CreateFileA(name, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL) */
    R_ebx = R_eax;
    PUSH(0); PUSH(0x00500200u); PUSH(24u); PUSH(0x00500100u); PUSH(R_ebx);
    CALL_SLOT(0x402108u, 0x401020u);                                    /* WriteFile(file, text, 24, &written, NULL) */
    PUSH(R_ebx);
    CALL_SLOT(0x40210cu, 0x401030u);                                    /* CloseHandle(file) */
    PUSH(RD32(0x00500200u) == 24u ? 7u : 9u);
    CALL_SLOT(0x402100u, 0x401040u);                                    /* ExitProcess(7: it was all written) */
    LIFT_RET(0x401000u);
    lift_ret_edx = R_edx;
    return R_eax;
}

const LiftedFn LIFTED[] = {{"stub_main", STUB_MAIN, lifted_stub_main}, {"stub_sum", STUB_SUM, lifted_stub_sum}, {"stub_call", STUB_CALL, lifted_stub_call}, {"stub_x87", STUB_X87, lifted_stub_x87}, {0, 0, 0}};
const int LIFTED_COUNT = 4;
const char LIFT_PROGRAM[] = "STUB";
const CalleeRow LIFT_CALLEES[] = {{0, 0, 0}};
const int LIFT_CALLEE_COUNT = 0;
const CalleeRow LIFT_FUNCTIONS[] = {{STUB_MAIN, 0, 0}, {STUB_SUM, 2, 0}, {STUB_CALL, 3, 0}, {STUB_X87, 2, 0}, {0, 0, 0}};
const int LIFT_FUNCTION_COUNT = 4;
const LiftImportSig LIFT_IMPORT_SIGS[] = {{"kernel32.dll", "ExitProcess", 1, 4}, {"kernel32.dll", "CreateFileA", 7, 28}, {"kernel32.dll", "WriteFile", 5, 20},
                                          {"kernel32.dll", "CloseHandle", 1, 4}, {0, 0, 0, 0}};
const int LIFT_IMPORT_SIG_COUNT = 4;
