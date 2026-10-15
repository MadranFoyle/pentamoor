import sys, time, os, argparse, random
sys.path.insert(0, "tools/soak")
import soak
S = os.environ["S"]
a = argparse.Namespace(res="800x600", minutes=10, repo=os.getcwd(), exe="src/port/build/pentamoor-run", module=None, program="sources/installed/Magic/Program/MAGIC.EXE",
    workdir=S+"/win/run", seed=3, duels_per_game=1, min_turns=3, max_turns=9, max_duel_s=300, stall_s=60, tick_s=1.0, verbose=True)
sk = soak.Soak(a)
g = sk.new_game(); sk.to_ante()
g.shot(S+"/win/00-ante.png")
assert sk.start_duel_from_ante(True)
ctx={"n":0}; prev=None; n=0
t0=time.time()
while time.time()-t0 < 330:
    t = sk.look("x")
    if t is None: break
    s = sk.sig(t)
    if s!=prev: prev=s; ctx={"n":0}
    life=None
    if s[6]:
        g.poke(0x6ff194, 1)
        life = (g.peek(0x6a3f7c,1), g.peek(0x6ff194,1))
    b = t.bar()
    if b and b[0].title and "main phase (before" in b[0].title.lower() and b[2]:
        ctx["limit"]=8
    if b and b[0].title and "CASTING" in b[0].title: ctx["mode"]="pay"; ctx["n"]=max(ctx["n"],1)
    desc,kind = sk.tick(t, ctx)
    if kind!="none": ctx["n"]+=1
    print(round(time.time()-t0), life, kind, desc, [d[0] for d in s[2]], flush=True)
    if not s[6] or s[2]:
        n+=1; g.shot("%s/win/%03d-%s.png"%(S,n,kind))
    if kind=="none" and not s[6]:
        g.key("return")
    time.sleep(1)
g.shot(S+"/win/final.png")
g.stop()
