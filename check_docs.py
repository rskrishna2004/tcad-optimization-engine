#!/usr/bin/env python
"""check_docs.py -- verify the documentation set before committing it.

Run this from the repository root, after copying an update in and before
`git commit`. It answers four questions that are easy to get wrong by hand:

  1. does every relative markdown link point at a file that exists?
  2. does every document keep to plain keyboard characters?
  3. does every document in the GAA chain link back to the route map?
  4. does the engine import, and does it report the version the README claims?

It exits non-zero if anything fails, so it can go in a pre-commit hook.

Works on Python 2.7 and 3.x, because simulator hosts are often old.
"""

from __future__ import print_function

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# A markdown link with a relative target: [text](path) or [text](path#anchor).
# Skips anything starting with a scheme, a slash, or a hash.
LINK = re.compile(r"\[[^\]]*\]\((?!https?://|mailto:|/|#)([^)\s]+)\)")

# The GAA chain. Every one of these must link back to the route map.
CHAIN = [
    "GAA_COMPACT_MODEL.md",
    "GAA_WHAT_YOU_NEED.md",
    "GAA_REFERENCE_DATA.md",
    "GAA_MODEL_CARD.md",
    "GAA_FIRST_RUN.md",
    "GAA_EXTRACTION_ORDER.md",
    "GAA_FREE_ZONE.md",
    "GAA_CHARGE_PARTITION.md",
    "GAA_CHECKING_RESULTS.md",
    "GAA_TROUBLESHOOTING.md",
]

# Characters that are not on a keyboard and should not be in these files.
# Written as code points so that this file is itself plain ASCII, which means
# it never trips its own check and it opens cleanly on any interpreter.
BANNED = dict((chr(c), name) for c, name in [
    (0x2014, "em dash"),
    (0x2013, "en dash"),
    (0x2018, "left single quote"),
    (0x2019, "right single quote"),
    (0x201c, "left double quote"),
    (0x201d, "right double quote"),
    (0x2026, "ellipsis"),
    (0x00b7, "middle dot"),
    (0x2192, "right arrow"),
    (0x2190, "left arrow"),
    (0x00d7, "multiplication sign"),
    (0x2248, "approximately equal"),
    (0x2264, "less than or equal"),
    (0x2265, "greater than or equal"),
    (0x00a0, "non-breaking space"),
    (0x2022, "bullet"),
    (0x00ad, "soft hyphen"),
])


def md_files():
    """Every markdown file in the repository, excluding anything hidden."""
    out = []
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in sorted(files):
            if fn.lower().endswith(".md"):
                out.append(os.path.join(root, fn))
    return sorted(out)


def rel(path):
    return os.path.relpath(path, HERE)


def check_links(paths):
    """Every relative link resolves to a file that is really there."""
    bad = []
    n = 0
    for p in paths:
        text = io.open(p, encoding="utf-8").read()
        base = os.path.dirname(p)
        for target in LINK.findall(text):
            n += 1
            clean = target.split("#", 1)[0]
            if not clean:
                continue
            full = os.path.normpath(os.path.join(base, clean))
            if not os.path.exists(full):
                bad.append((rel(p), target))
    return n, bad


def check_characters(paths):
    """No characters that a keyboard cannot type.

    Fenced code blocks are skipped, because a fence may be quoting real tool
    output that contains such a character on purpose. `tools/plain_text_md.py`
    uses the same rule, so the two agree.
    """
    bad = []
    for p in paths:
        text = io.open(p, encoding="utf-8").read()
        in_fence = False
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for ch, name in BANNED.items():
                if ch in line:
                    bad.append((rel(p), i, name, line.strip()[:60]))
    return bad


def check_chain(docs_dir):
    """Every page of the GAA chain exists and links back to the route map."""
    missing, unlinked = [], []
    for fn in CHAIN:
        p = os.path.join(docs_dir, fn)
        if not os.path.exists(p):
            missing.append(fn)
            continue
        if fn == CHAIN[0]:
            continue
        text = io.open(p, encoding="utf-8").read()
        if CHAIN[0] not in text:
            unlinked.append(fn)
    return missing, unlinked


def check_engine():
    """The engine imports and reports a version."""
    sys.path.insert(0, HERE)
    try:
        import tcadopt
    except Exception as exc:
        return None, "%s: %s" % (type(exc).__name__, exc)
    return getattr(tcadopt, "__version__", None), None


def readme_version():
    """The version the README claims, so the two can be compared."""
    p = os.path.join(HERE, "README.md")
    if not os.path.exists(p):
        return None
    text = io.open(p, encoding="utf-8").read()
    m = re.search(r"\*\*version ([0-9]+\.[0-9]+\.[0-9]+)\*\*", text) \
        or re.search(r"version \*\*([0-9]+\.[0-9]+\.[0-9]+)\*\*", text)
    return m.group(1) if m else None


def main():
    paths = md_files()
    problems = 0

    print("checking %d markdown file(s)" % len(paths))
    print("")

    # 1. links
    n_links, bad_links = check_links(paths)
    if bad_links:
        problems += len(bad_links)
        print("BROKEN LINKS (%d of %d):" % (len(bad_links), n_links))
        for f, t in bad_links:
            print("   %-34s -> %s" % (f, t))
    else:
        print("links          : %d checked, all resolve" % n_links)

    # 2. characters
    bad_chars = check_characters(paths)
    if bad_chars:
        problems += len(bad_chars)
        print("")
        print("CHARACTERS THAT ARE NOT ON A KEYBOARD (%d):" % len(bad_chars))
        for f, i, name, snip in bad_chars[:40]:
            print("   %s:%d  %s" % (f, i, name))
            print("        %s" % snip)
        if len(bad_chars) > 40:
            print("   ... and %d more" % (len(bad_chars) - 40))
    else:
        print("characters     : plain ASCII punctuation throughout")

    # 3. the chain
    docs_dir = os.path.join(HERE, "docs")
    missing, unlinked = check_chain(docs_dir)
    if missing or unlinked:
        problems += len(missing) + len(unlinked)
        print("")
        for fn in missing:
            print("MISSING from the GAA chain: docs/%s" % fn)
        for fn in unlinked:
            print("NO LINK BACK to the route map: docs/%s" % fn)
    else:
        print("GAA chain      : %d pages, every one links back" % len(CHAIN))

    # 4. the engine
    ver, err = check_engine()
    claimed = readme_version()
    if err:
        problems += 1
        print("")
        print("ENGINE WILL NOT IMPORT: %s" % err)
    else:
        print("engine         : imports, reports %s" % ver)
        if claimed and ver and claimed != ver:
            problems += 1
            print("")
            print("VERSION MISMATCH: README says %s, the package says %s"
                  % (claimed, ver))
        elif claimed:
            print("README         : claims %s, which matches" % claimed)

    print("")
    if problems:
        print("%d problem(s). Fix them before committing." % problems)
        return 1
    print("ALL CHECKS PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
