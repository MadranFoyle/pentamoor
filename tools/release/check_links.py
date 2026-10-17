#!/usr/bin/env python3
"""
check_links.py - fail if a link in a tracked Markdown file points at something that is not there.

    python3 tools/release/check_links.py            # every .md file git tracks, in the repository this file is in
    python3 tools/release/check_links.py --root DIR # every .md file under DIR

What is looked at: inline links and images, `[text](target)`, and reference definitions, `[label]: target`. A link is fine when
  * it is a web link (http:, https:, mailto:) -- not fetched, CI has no business with the network;
  * it names a file or a folder that exists, relative to the file that holds the link (or to the root, if it starts with `/`);
  * it is `#anchor` or `file.md#anchor`, and that Markdown file has a heading that GitHub would give that anchor.
Links inside fenced code blocks and inline code are examples, not links, and are skipped. Only Markdown is checked (the documents
a reader follows by clicking); paths written in backticks are prose and are not looked at.
"""
import argparse
import os
import re
import subprocess
import sys
import urllib.parse

INLINE = re.compile(r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*(<[^>]*>|[^()\s]*(?:\([^()\s]*\)[^()\s]*)*)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
REFDEF = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(<[^>]*>|\S+)")
FENCE = re.compile(r"^ {0,3}(```+|~~~+)")
HEADING = re.compile(r"^ {0,3}#{1,6}\s+(.*?)\s*#*\s*$")
CODE_SPAN = re.compile(r"(`+)(?:(?!\1).)+?\1")
EXTERNAL = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def tracked_markdown(repo):
    out = subprocess.run(["git", "ls-files", "-z", "*.md"], cwd=repo, check=True, stdout=subprocess.PIPE).stdout
    return sorted(p for p in out.decode("utf-8", "surrogateescape").split("\0") if p)


def all_markdown(root):
    found = []
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            if f.lower().endswith(".md"):
                found.append(os.path.relpath(os.path.join(dirpath, f), root).replace(os.sep, "/"))
    return sorted(found)


def github_anchor(heading):
    """The anchor GitHub gives a heading: markup dropped, lower case, punctuation removed, spaces to hyphens."""
    h = re.sub(r"`([^`]*)`", r"\1", heading)
    h = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", h)
    h = re.sub(r"[*~]", "", h).strip().lower()                         # underscores stay: GitHub keeps them
    h = re.sub(r"[^\w\- ]", "", h, flags=re.UNICODE)
    return h.replace(" ", "-")


def anchors_of(text):
    seen = {}
    out = set()
    in_fence = False
    for line in text.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING.match(line)
        if m:
            a = github_anchor(m.group(1))
            n = seen.get(a, 0)
            seen[a] = n + 1
            out.add(a if n == 0 else f"{a}-{n}")
        for m in re.finditer(r"<a\s+(?:name|id)=\"([^\"]+)\"", line):
            out.add(m.group(1))
    return out


def links_of(text):
    """(line number, target) for every link in the text that is not in code."""
    found = []
    in_fence = False
    prev_blank, in_indented = True, False
    for no, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        indented = line.startswith(("    ", "\t")) and line.strip() != ""
        if indented and (prev_blank or in_indented):               # an indented code block (a list's continuation is skipped with it: a miss, never a false alarm)
            in_indented = True
            continue
        in_indented = False
        prev_blank = line.strip() == ""
        bare = CODE_SPAN.sub(lambda m: " " * len(m.group(0)), line)
        m = REFDEF.match(bare)
        if m:
            found.append((no, m.group(1)))
        for m in INLINE.finditer(bare):
            found.append((no, m.group(1)))
    return found


def check(root, files=None):
    """Every broken link under root, as sentences: 'file:line: target: what is wrong'."""
    files = all_markdown(root) if files is None else files
    texts = {}

    def text(path):
        if path not in texts:
            with open(os.path.join(root, path), encoding="utf-8", errors="replace") as f:
                texts[path] = f.read()
        return texts[path]

    problems = []
    for path in files:
        for no, target in links_of(text(path)):
            t = target[1:-1] if target.startswith("<") and target.endswith(">") else target
            if not t or EXTERNAL.match(t):
                continue
            ref, _, frag = t.partition("#")
            ref = urllib.parse.unquote(ref)
            frag = urllib.parse.unquote(frag)
            if ref.split("?")[0] == "":
                dest = path
            else:
                ref = ref.split("?")[0]
                base = root if ref.startswith("/") else os.path.join(root, os.path.dirname(path))
                dest = os.path.normpath(os.path.join(base, ref.lstrip("/")))
                dest = os.path.relpath(dest, root).replace(os.sep, "/")
                if dest.startswith("..") or not os.path.exists(os.path.join(root, dest)):
                    problems.append(f"{path}:{no}: {target}: no such file or folder")
                    continue
            if frag:
                if not dest.lower().endswith(".md") or not os.path.isfile(os.path.join(root, dest)):
                    continue                      # an anchor in something that is not Markdown (or a folder) is not ours to check
                if frag.lower() not in anchors_of(text(dest)):
                    problems.append(f"{path}:{no}: {target}: {dest} has no heading #{frag}")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", help="check every .md file under this folder instead of what git tracks")
    args = ap.parse_args()
    if args.root:
        root, files = os.path.abspath(args.root), None
    else:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        files = tracked_markdown(root)
    problems = check(root, files)
    print(f"check_links: {len(files) if files is not None else len(all_markdown(root))} Markdown files looked at")
    if problems:
        print("\nBROKEN LINKS:\n  " + "\n  ".join(problems))
        sys.exit(1)
    print("check_links: every link resolves")


if __name__ == "__main__":
    main()
