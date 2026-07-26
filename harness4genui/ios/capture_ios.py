"""Drive the Wikipedia iOS app on a booted simulator and dump its accessibility tree.

Runs on a GitHub-hosted macOS runner. Mirrors the Android capture exactly: controls are
addressed by their ACCESSIBLE LABEL, which is the same addressing the contract uses, so
navigation and checking speak one vocabulary.

Screens dumped: launch, search, search-active (field focused). The focused state matters,
because on Android the search field is not a text-entry node until it is focused, and we want
to know whether iOS behaves the same way.

Usage: python3 capture_ios.py <UDID> <outdir>
"""
import json
import subprocess
import sys
import time
from pathlib import Path


def describe(udid, outdir, tag):
    r = subprocess.run(["idb", "ui", "describe-all", "--udid", udid, "--json"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  describe-all failed for {tag}: {r.stderr[:300]}")
        return []
    els = []
    out = r.stdout.strip()
    try:
        parsed = json.loads(out)
        els = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    els.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    Path(outdir, f"ios-{tag}.json").write_text(json.dumps(els, indent=1), encoding="utf-8")
    print(f"  {tag}: {len(els)} elements")
    return els


def label(el):
    for k in ("AXLabel", "title", "AXValue", "label"):
        v = el.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def find(els, *needles):
    for el in els:
        lab = label(el).lower()
        for n in needles:
            if n.lower() in lab:
                return el
    return None


def tap(udid, el):
    f = el.get("frame") or el.get("AXFrame") or {}
    x = int(f.get("x", 0) + f.get("width", 0) / 2)
    y = int(f.get("y", 0) + f.get("height", 0) / 2)
    subprocess.run(["idb", "ui", "tap", "--udid", udid, str(x), str(y)],
                   capture_output=True, text=True)
    time.sleep(3)


def main():
    udid, outdir = sys.argv[1], sys.argv[2]
    Path(outdir).mkdir(parents=True, exist_ok=True)

    els = describe(udid, outdir, "launch")

    # Dismiss onboarding or promo screens, addressed by accessible label.
    for _ in range(6):
        b = find(els, "Skip", "Get started", "Continue", "Close", "Not now", "Done")
        if b is None:
            break
        print(f"  dismissing {label(b)[:40]!r}")
        tap(udid, b)
        els = describe(udid, outdir, "launch")

    s = find(els, "Search")
    if s is None:
        print("  no Search control found; launch dump captured, stopping here")
        return 0

    tap(udid, s)
    els = describe(udid, outdir, "search")

    # Dismiss anything that appeared on the search screen, then focus the field.
    c = find(els, "Close", "Not now", "Skip")
    if c is not None:
        tap(udid, c)
        els = describe(udid, outdir, "search")

    f = find(els, "Search Wikipedia", "Search")
    if f is not None:
        tap(udid, f)
        describe(udid, outdir, "search-active")
    return 0


if __name__ == "__main__":
    sys.exit(main())
