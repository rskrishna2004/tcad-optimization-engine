#!/usr/bin/env python
"""plain_text_md.py -- replace typographic characters with keyboard ones.

Markdown files pick up em dashes, curly quotes, arrows and middle dots from
editors and from copy-paste. None of those are on a keyboard, and a document
set that mixes them reads as though it came from somewhere else.

This walks every .md file under a directory and replaces them with the plain
ASCII equivalent. It never touches a code fence, because a code fence may be
quoting real output that contains those characters on purpose.

    python tools/plain_text_md.py --check      # report only, change nothing
    python tools/plain_text_md.py              # rewrite in place

Run it from the repository root. It exits non-zero in --check mode if anything
would change, so it can go in a pre-commit hook.

Needs Python 3.6 or newer.
"""

from __future__ import print_function

import io
import os
import sys

# Each entry is the code point, its plain replacement, and a readable name.
# Written as code points so that this file is itself plain ASCII: a tool that
# removes these characters should not contain any, or it trips its own check.
RULES = [(chr(c), r, n) for c, r, n in [
    (0x2014, "-",   "em dash"),
    (0x2013, "-",   "en dash"),
    (0x2018, "'",   "left single quote"),
    (0x2019, "'",   "right single quote"),
    (0x201c, '"',   "left double quote"),
    (0x201d, '"',   "right double quote"),
    (0x2026, "...", "ellipsis"),
    (0x00b7, ".",   "middle dot"),
    (0x2022, "-",   "bullet"),
    (0x2192, "->",  "right arrow"),
    (0x2190, "<-",  "left arrow"),
    (0x00d7, "x",   "multiplication sign"),
    (0x2248, "~",   "approximately equal"),
    (0x2264, "<=",  "less than or equal"),
    (0x2265, ">=",  "greater than or equal"),
    (0x00a0, " ",   "non-breaking space"),
    (0x00ad, "",    "soft hyphen"),
]]


def md_files(root):
    out = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in sorted(files):
            if fn.lower().endswith(".md"):
                out.append(os.path.join(base, fn))
    return sorted(out)


def convert(text):
    """Return (new_text, [(line_no, name)]) leaving fenced blocks alone."""
    hits = []
    out = []
    in_fence = False
    for i, line in enumerate(text.split(u"\n"), 1):
        stripped = line.lstrip()
        if stripped.startswith(u"```") or stripped.startswith(u"~~~"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        new = line
        for ch, repl, name in RULES:
            if ch in new:
                hits.append((i, name))
                new = new.replace(ch, repl)
        out.append(new)
    return u"\n".join(out), hits


def main(argv):
    check_only = "--check" in argv
    root = os.getcwd()
    total = 0
    touched = 0

    for path in md_files(root):
        text = io.open(path, encoding="utf-8").read()
        new, hits = convert(text)
        if not hits:
            continue
        touched += 1
        total += len(hits)
        rel = os.path.relpath(path, root)
        names = {}
        for _, name in hits:
            names[name] = names.get(name, 0) + 1
        summary = ", ".join("%d %s" % (n, k) for k, n in sorted(names.items()))
        print("%-38s %s" % (rel, summary))
        if not check_only:
            io.open(path, "w", encoding="utf-8").write(new)

    print("")
    if not total:
        print("Every markdown file is already plain keyboard text.")
        return 0
    if check_only:
        print("%d character(s) in %d file(s) would change. "
              "Run without --check to do it." % (total, touched))
        return 1
    print("Replaced %d character(s) in %d file(s)." % (total, touched))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
