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


def frontmost(udid):
    """Return the AXLabel of the frontmost Application element, or None."""
    r = subprocess.run(["idb", "ui", "describe-all", "--udid", udid, "--json"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    out = r.stdout.strip()
    try:
        els = json.loads(out)
        if isinstance(els, dict):
            els = [els]
    except json.JSONDecodeError:
        els = [json.loads(l) for l in out.splitlines() if l.strip().startswith("{")]
    for e in els:
        if e.get("type") == "Application":
            return (e.get("AXLabel") or "").strip()
    return None


def relaunch(udid, bundle_id, want="Wikipedia"):
    """Foreground the app and wait until IT, not something else, is frontmost.

    An earlier version polled only on node count. The app failed to foreground, the poll
    accepted the iOS home screen as a populated tree, the navigation step then matched the
    home-screen Search slider, and the run captured Spotlight. Checking identity rather than
    size is the difference between data and garbage.
    """
    subprocess.run(["xcrun", "simctl", "terminate", udid, bundle_id],
                   capture_output=True, text=True)
    time.sleep(2)
    r = subprocess.run(["xcrun", "simctl", "launch", udid, bundle_id],
                       capture_output=True, text=True)
    print(f"  launch rc={r.returncode} out={r.stdout.strip()[:120]} err={r.stderr.strip()[:160]}")

    for attempt in range(24):
        time.sleep(5)
        app = frontmost(udid)
        print(f"  wait {attempt}: frontmost={app!r}")
        if app and want.lower() in app.lower():
            return True
        # If the app died, say so loudly rather than capturing whatever is on screen.
        chk = subprocess.run(["xcrun", "simctl", "spawn", udid, "launchctl", "list"],
                             capture_output=True, text=True)
        if bundle_id not in chk.stdout and attempt >= 3:
            print(f"  {bundle_id} is not in launchctl list; relaunching")
            subprocess.run(["xcrun", "simctl", "launch", udid, bundle_id],
                           capture_output=True, text=True)
    return False



def describe_point_full(udid, x, y):
    """Return (type, AXLabel) at a screen point, so an UNLABELLED control is distinguishable
    from no control at all. Reporting only the label made an unnamed search field look like an
    empty region."""
    r = subprocess.run(["idb", "ui", "describe-point", "--udid", udid,
                        str(int(x)), str(int(y)), "--json"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return ("", "")
    try:
        d = json.loads(r.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return ("", "")
    if isinstance(d, list):
        d = d[0] if d else {}
    return ((d.get("type") or "").strip(),
            (d.get("AXLabel") or d.get("title") or d.get("AXValue") or "").strip())


def describe_point(udid, x, y):
    """What is at this screen point? Returns the AXLabel, or ''. """
    r = subprocess.run(["idb", "ui", "describe-point", "--udid", udid,
                        str(int(x)), str(int(y)), "--json"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return ""
    try:
        d = json.loads(r.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return ""
    if isinstance(d, list):
        d = d[0] if d else {}
    return (d.get("AXLabel") or d.get("title") or "").strip()


def find_in_tab_bar(udid, els, want="Search"):
    """Locate a tab by ACCESSIBLE LABEL inside a tab bar whose children the flat dump omits.

    idb's describe-all returned the Tab Bar container but not its individual tabs, so the tab
    cannot be found by scanning the dump. Rather than guess a coordinate, probe each slot with
    describe-point and match on the label, keeping the same addressing discipline the contract
    uses.
    """
    bar = None
    for e in els:
        if (e.get("AXLabel") or "").strip() == "Tab Bar":
            bar = e
            break
    if bar is None:
        return None
    f = bar.get("frame") or {}
    x0, y0 = f.get("x", 0), f.get("y", 0)
    w, h = f.get("width", 0), f.get("height", 0)
    if not w or not h:
        return None
    y = y0 + h * 0.4
    for slots in (5, 4, 6):
        for i in range(slots):
            x = x0 + w * (i + 0.5) / slots
            label = describe_point(udid, x, y)
            if label:
                print(f"    tab probe {slots}/{i}: {label!r}")
            if label and want.lower() in label.lower():
                return (x, y)
    return None



def probe_grid(udid, outdir, tag, width=402, height=874):
    """Sweep the screen with describe-point and record every distinct element found.

    Necessary because idb's describe-all does NOT return the complete tree: on the Wikipedia
    iOS search screen it omits the search field entirely, both before and after focus, even
    though describe-point at that location reports
    type='TextField' AXLabel='Search Wikipedia'. Building the iOS surface from describe-all
    alone would therefore report a meaning as absent that is plainly present. Both queries come
    from the same idb accessibility API; the sweep is simply the exhaustive one.
    """
    seen, found = set(), []
    for y in range(40, int(height), 24):
        for x in (int(width * f) for f in (0.15, 0.5, 0.85)):
            typ, lab = describe_point_full(udid, x, y)
            if not typ and not lab:
                continue
            key = (typ, lab)
            if key in seen:
                continue
            seen.add(key)
            found.append({"type": typ, "AXLabel": lab, "x": x, "y": y})
    Path(outdir, f"ios-{tag}-probes.json").write_text(
        json.dumps(found, indent=1), encoding="utf-8")
    print(f"  {tag} probe sweep: {len(found)} distinct elements")
    for f in found:
        print(f"     {f['type']:<16} {f['AXLabel'][:44]!r}")
    return found


def main():
    udid, outdir = sys.argv[1], sys.argv[2]
    bundle_id = sys.argv[3] if len(sys.argv) > 3 else "org.wikimedia.wikipedia"
    Path(outdir).mkdir(parents=True, exist_ok=True)

    if not relaunch(udid, bundle_id):
        print("  FAILED: the Wikipedia app never became frontmost. Dumping whatever is on")
        print("  screen for diagnosis ONLY; it is not the app and must not be used as data.")
        describe(udid, outdir, "NOT-THE-APP-diagnostic")
        return 1

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
    if s is not None:
        tap(udid, s)
    else:
        pt = find_in_tab_bar(udid, els, "Search")
        if pt is None:
            print("  no Search control found in the dump or the tab bar; stopping here")
            return 0
        print(f"  tapping Search tab at {pt}")
        subprocess.run(["idb", "ui", "tap", "--udid", udid,
                        str(int(pt[0])), str(int(pt[1]))], capture_output=True, text=True)
        time.sleep(3)
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

    # The search field is not in the flat dump on this screen, exactly as on Android where the
    # field is not a text-entry node until focused. Probe down the top of the screen by
    # accessible label to find it rather than guessing a coordinate.
    app = next((e for e in els if e.get("type") == "Application"), None)
    width = ((app or {}).get("frame") or {}).get("width", 402)
    for y in range(50, 320, 15):
        # NB: do not name this `label`. That shadows the module-level label() function for the
        # whole of main(), and the earlier label(b) call then dies with UnboundLocalError.
        typ, lab = describe_point_full(udid, width / 2, y)
        if typ or lab:
            print(f"    top probe y={y}: type={typ!r} label={lab!r}")
        if typ in ("TextField", "SearchField", "SecureTextField") or (lab and "search" in lab.lower()):
            print(f"  tapping search field at (({width/2}, {y}))")
            subprocess.run(["idb", "ui", "tap", "--udid", udid,
                            str(int(width / 2)), str(y)], capture_output=True, text=True)
            time.sleep(3)
            describe(udid, outdir, "search-active")
            probe_grid(udid, outdir, "search-active")
            return 0
    print("  search field not found by probing; search dump captured without focus")
    return 0


if __name__ == "__main__":
    sys.exit(main())
