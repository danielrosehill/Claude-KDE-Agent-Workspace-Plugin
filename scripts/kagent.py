#!/usr/bin/python3
"""kagent — run an AI agent's GUI work on its own KDE Plasma virtual desktop.

Every subcommand prints JSON on stdout. Errors print {"error": ...} and exit 1.
Runs under the system interpreter on purpose: it needs python3-dbus, python3-gi
and gir1.2-atspi-2.0, which are distro packages, not pip packages.

Verified on Plasma 6.6.6 / KWin 6.6.6 / Wayland / Ubuntu 26.04, 2026-10-19.
See reference/findings.md for what each mechanism can and cannot do.
"""

import argparse
import warnings
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import uuid
import zlib
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)  # Atspi.Action.get_action_name etc.

KWIN = "org.kde.KWin"
VDM_PATH = "/VirtualDesktopManager"
VDM_IFACE = "org.kde.KWin.VirtualDesktopManager"
PROPS = "org.freedesktop.DBus.Properties"

DEFAULT_NAMES = ["Claude", "AI Agents"]
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kde-agent-workspace"
CONFIG_FILE = CONFIG_DIR / "config.json"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
HELPER_DIR = DATA_DIR / "kde-agent-workspace" / "bin"
HELPER_BIN = HELPER_DIR / "kagent-capture"
HELPER_DESKTOP = DATA_DIR / "applications" / "kagent-capture.desktop"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "kde-agent-workspace"


class KagentError(Exception):
    pass


def out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------- D-Bus / KWin

def _bus():
    import dbus
    return dbus.SessionBus()


def vdm_get(prop):
    obj = _bus().get_object(KWIN, VDM_PATH)
    return obj.Get(VDM_IFACE, prop, dbus_interface=PROPS)


def vdm_set(prop, value):
    obj = _bus().get_object(KWIN, VDM_PATH)
    obj.Set(VDM_IFACE, prop, value, dbus_interface=PROPS)


def vdm_call(method, *args):
    obj = _bus().get_object(KWIN, VDM_PATH)
    return getattr(obj, method)(*args, dbus_interface=VDM_IFACE)


def desktops():
    """[{position, id, name}] — `desktops` is a property of type a(uss), not a method."""
    return [{"position": int(p), "id": str(i), "name": str(n)} for p, i, n in vdm_get("desktops")]


def current_desktop_id():
    return str(vdm_get("current"))


def run_kwin_script(body, timeout=3.0):
    """Run a KWin JS snippet whose `return` value comes back as parsed JSON.

    KWin's print() goes to the user journal as `js: <text>`; we tag it with a
    nonce and read it back. Load → run → unload, one throwaway plugin name per call.
    """
    nonce = uuid.uuid4().hex[:12]
    marker = f"KAGENT-{nonce}"
    src = (
        "(function(){ var __r; try { __r = (function(){\n" + body + "\n})(); }"
        " catch (e) { __r = {__error: String(e)}; }"
        f" print('{marker} ' + JSON.stringify(__r === undefined ? null : __r)); }})();\n"
    )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"script-{nonce}.js"
    path.write_text(src)
    since = f"@{int(time.time()) - 1}"
    bus = _bus()
    scripting = bus.get_object(KWIN, "/Scripting")
    plugin = f"kagent-{nonce}"
    try:
        # loadScript is overloaded (s) / (ss); introspection-driven proxies pick (s) and fail.
        sid = int(bus.call_blocking(KWIN, "/Scripting", "org.kde.kwin.Scripting", "loadScript",
                                    "ss", (str(path), plugin)))
        if sid < 0:
            raise KagentError("KWin refused to load the script")
        bus.get_object(KWIN, f"/Scripting/Script{sid}").run(dbus_interface="org.kde.kwin.Script")
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.15)
            log = subprocess.run(["journalctl", "--user", "--since", since, "-o", "cat", "--no-pager"],
                                 capture_output=True, text=True).stdout
            for line in log.splitlines():
                idx = line.find(marker + " ")
                if idx >= 0:
                    res = json.loads(line[idx + len(marker) + 1:])
                    if isinstance(res, dict) and "__error" in res:
                        raise KagentError("KWin script error: " + res["__error"])
                    return res
        raise KagentError("no output from KWin script (is the user journal readable?)")
    finally:
        try:
            scripting.unloadScript(plugin, dbus_interface="org.kde.kwin.Scripting")
        except Exception:
            pass
        path.unlink(missing_ok=True)


JS_WINDOW = """
function winInfo(w) {
  return {handle: w.internalId.toString(), pid: w.pid, resourceClass: w.resourceClass,
          caption: w.caption, output: w.output ? w.output.name : null,
          desktops: w.desktops.map(function(d){return d.id;}), onAllDesktops: w.onAllDesktops,
          minimized: w.minimized, active: w.active,
          transientFor: w.transientFor ? w.transientFor.internalId.toString() : null,
          geometry: {x: w.frameGeometry.x, y: w.frameGeometry.y,
                     width: w.frameGeometry.width, height: w.frameGeometry.height}};
}
function findWin(h) {
  var l = workspace.windowList();
  for (var i = 0; i < l.length; i++) if (l[i].internalId.toString() == h) return l[i];
  return null;
}
function findDesk(id) {
  var l = workspace.desktops;
  for (var i = 0; i < l.length; i++) if (l[i].id == id) return l[i];
  return null;
}
function findOutput(name) {
  var l = workspace.screens;
  for (var i = 0; i < l.length; i++) if (l[i].name == name) return l[i];
  return null;
}
"""


def kwin_windows():
    return run_kwin_script(JS_WINDOW + """
return workspace.windowList().filter(function(w){return w.normalWindow || w.dialog;}).map(winInfo);
""")


def kwin_outputs():
    return run_kwin_script("""
var active = workspace.activeScreen ? workspace.activeScreen.name : null;
return workspace.screens.map(function(o){
  var cur = (typeof workspace.currentDesktopForScreen === 'function') ? workspace.currentDesktopForScreen(o) : null;
  return {name: o.name, manufacturer: o.manufacturer, model: o.model, active: o.name == active,
          geometry: {x: o.geometry.x, y: o.geometry.y, width: o.geometry.width, height: o.geometry.height},
          currentDesktop: cur ? cur.id : null};
});
""")


# ---------------------------------------------------------------- environment

def plasma_version():
    try:
        v = subprocess.run(["plasmashell", "--version"], capture_output=True, text=True).stdout.split()[-1]
        return v, tuple(int(x) for x in v.split(".")[:2])
    except Exception:
        return None, (0, 0)


def kread(file, group, key):
    r = subprocess.run(["kreadconfig6", "--file", file, "--group", group, "--key", key],
                       capture_output=True, text=True)
    return r.stdout.strip()


def per_output_state():
    ver, vt = plasma_version()
    supported = vt >= (6, 7)
    enabled = kread("kwinrc", "Windows", "PerOutputVirtualDesktops").lower() == "true"
    return {"plasma": ver, "supported": supported, "enabled": supported and enabled}


# ---------------------------------------------------------------- agent desktop

def load_config():
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n")


def agent_desktop(required=True):
    cfg = load_config()
    ds = desktops()
    if cfg.get("desktop_id"):
        for d in ds:
            if d["id"] == cfg["desktop_id"]:
                return d
    names = [cfg["desktop_name"]] if cfg.get("desktop_name") else DEFAULT_NAMES
    for n in names:
        for d in ds:
            if d["name"] == n:
                return d
    if required:
        raise KagentError("no agent desktop found — run `kagent.py create --name Claude` first")
    return None


# ---------------------------------------------------------------- subcommands

def cmd_status(a):
    ds = desktops()
    cur = current_desktop_id()
    wins = kwin_windows()
    ag = agent_desktop(required=False)
    for d in ds:
        d["current"] = d["id"] == cur
        d["windows"] = sum(1 for w in wins if d["id"] in w["desktops"] or w["onAllDesktops"])
        d["agent"] = bool(ag and ag["id"] == d["id"])
    out({
        "session": os.environ.get("XDG_SESSION_TYPE"),
        "desktop_environment": os.environ.get("XDG_CURRENT_DESKTOP"),
        "per_output_desktops": per_output_state(),
        "rows": int(vdm_get("rows")),
        "desktops": ds,
        "outputs": kwin_outputs(),
        "agent_desktop": ag,
        "config": load_config(),
        "capture_helper_installed": HELPER_BIN.exists() and HELPER_DESKTOP.exists(),
    })


def cmd_create(a):
    name = a.name
    existing = next((d for d in desktops() if d["name"] == name), None)
    created = False
    if not existing:
        vdm_call("createDesktop", len(desktops()) if a.position is None else a.position, name)
        for _ in range(20):
            time.sleep(0.1)
            existing = next((d for d in desktops() if d["name"] == name), None)
            if existing:
                break
        if not existing:
            raise KagentError("createDesktop returned but no desktop appeared")
        created = True
    cfg = load_config()
    cfg.update({"desktop_name": name, "desktop_id": existing["id"]})
    save_config(cfg)
    out({"created": created, "desktop": existing, "config_file": str(CONFIG_FILE)})


def cmd_rename(a):
    d = agent_desktop()
    vdm_call("setDesktopName", d["id"], a.name)
    cfg = load_config()
    cfg["desktop_name"] = a.name
    cfg["desktop_id"] = d["id"]
    save_config(cfg)
    out({"renamed": d["id"], "from": d["name"], "to": a.name})


def cmd_remove(a):
    d = agent_desktop()
    if d["id"] == current_desktop_id() and len(desktops()) > 1:
        other = next(x for x in desktops() if x["id"] != d["id"])
        vdm_set("current", other["id"])
    vdm_call("removeDesktop", d["id"])
    cfg = load_config()
    for k in ("desktop_id", "desktop_name"):
        cfg.pop(k, None)
    save_config(cfg)
    out({"removed": d})


def cmd_show(a):
    d = agent_desktop()
    prev = current_desktop_id()
    vdm_set("current", d["id"])
    out({"previous": prev, "current": d["id"]})


def cmd_switch(a):
    vdm_set("current", a.desktop_id)
    out({"current": current_desktop_id()})


def cmd_windows(a):
    wins = kwin_windows()
    if not a.all:
        d = agent_desktop()
        wins = [w for w in wins if d["id"] in w["desktops"] and not w["onAllDesktops"]]
    out(wins)


def _descendants(root):
    kids = {}
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            ppid = int((p / "stat").read_text().rsplit(")", 1)[1].split()[1])
        except Exception:
            continue
        kids.setdefault(ppid, []).append(int(p.name))
    seen, stack = {root}, [root]
    while stack:
        for c in kids.get(stack.pop(), []):
            if c not in seen:
                seen.add(c)
                stack.append(c)
    return seen


def move_window(handle, desktop_id=None, output=None, on_all=None):
    js = JS_WINDOW + f"""
var w = findWin({json.dumps(handle)});
if (!w) return {{__error: 'no window ' + {json.dumps(handle)}}};
var did = {json.dumps(desktop_id)}, oname = {json.dumps(output)}, onAll = {json.dumps(on_all)};
if (did) {{ var d = findDesk(did); if (!d) return {{__error: 'no desktop ' + did}}; w.desktops = [d]; }}
if (onAll !== null) w.onAllDesktops = onAll;
if (oname) {{ var o = findOutput(oname); if (!o) return {{__error: 'no output ' + oname}}; workspace.sendClientToScreen(w, o); }}
return winInfo(w);
"""
    return run_kwin_script(js)


def active_window():
    return run_kwin_script("return workspace.activeWindow ? workspace.activeWindow.internalId.toString() : null;")


def activate_window(handle):
    """Give a window keyboard focus. If it sits on another desktop, KWin switches the view there."""
    return run_kwin_script(JS_WINDOW + f"""
var w = findWin({json.dumps(handle)});
if (!w) return {{__error: 'no window ' + {json.dumps(handle)}}};
workspace.activeWindow = w;
return winInfo(w);
""")


def _new_windows(before, proc, any_new, wm_class=None):
    new = [w for w in kwin_windows() if w["handle"] not in before]
    # A new dialog transient for a pre-existing window belongs to the user (e.g. their
    # browser's Open File portal). Moving it drags its parent along, so never take one.
    new = [w for w in new if w.get("transientFor") not in before]
    if wm_class:
        new = [w for w in new if w["resourceClass"] == wm_class]
    tree = _descendants(proc.pid)
    # Single-instance / D-Bus-activated apps (konsole, chrome, dolphin…) open their
    # window from a process that is not our child — fall back to any new window.
    return [w for w in new if w["pid"] in tree] or (new if any_new else [])


def _spawn(argv):
    env = dict(os.environ)
    env["QT_LINUX_ACCESSIBILITY_ALWAYS_ON"] = "1"   # Qt apps skip AT-SPI registration without it
    env["QT_ACCESSIBILITY"] = "1"
    env.pop("NO_AT_BRIDGE", None)                    # GTK honours this to disable AT-SPI
    logs = CACHE_DIR / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f"{Path(argv[0]).name}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    proc = subprocess.Popen(argv, stdout=open(log, "wb"), stderr=subprocess.STDOUT, env=env,
                            start_new_session=True)
    return proc, log


def cmd_launch(a):
    d = agent_desktop()
    previous = active_window()
    before = {w["handle"] for w in kwin_windows()}
    proc, log = _spawn(a.argv)
    found, deadline = [], time.time() + a.timeout
    while time.time() < deadline:
        time.sleep(0.3)
        found = _new_windows(before, proc, a.any_new_window)
        if found:
            time.sleep(a.settle)
            found = _new_windows(before, proc, a.any_new_window) or found
            break
        if proc.poll() is not None and not a.any_new_window:
            break
    moved = [move_window(w["handle"], desktop_id=d["id"], output=a.output) for w in found]
    # A new window takes keyboard focus and keeps it after the move, so the user's typing
    # would land in a window they cannot see. Hand focus back.
    if moved and previous and not a.keep_focus:
        activate_window(previous)
    out({
        "pid": proc.pid,
        "exited": proc.poll(),
        "log": str(log),
        "agent_desktop": d,
        "windows": moved,
        "focus_returned_to": previous if moved and not a.keep_focus else None,
        "note": None if moved else "no new window matched — app may be single-instance (retry with --any-new-window), "
                                   "still starting (raise --timeout), CLI-only, or crashed (read the log)",
    })


def cmd_activate(a):
    out(activate_window(a.handle))


def cmd_close(a):
    out(run_kwin_script(JS_WINDOW + f"""
var w = findWin({json.dumps(a.handle)});
if (!w) return {{__error: 'no window ' + {json.dumps(a.handle)}}};
var info = winInfo(w);
w.closeWindow();
return info;
"""))


MD_BEGIN = "<!-- kde-agent-workspace:chrome:begin -->"
MD_END = "<!-- kde-agent-workspace:chrome:end -->"


def chrome_directive(desktop_name):
    script = Path(__file__).resolve()
    return f"""{MD_BEGIN}
## Claude in Chrome — use the agent workspace

When using Claude in Chrome (`mcp__claude-in-chrome__*`), work in a Chrome window on
the agent's own KDE virtual desktop, **{desktop_name}**, not in the user's active
workspace. Assume the main workspace (whatever desktop the user is on) is the user's
private workspace: do not open, move, focus or screenshot windows there.

Before the first browser call of a task, run the `use-chrome` skill (plugin
`kde-agent-workspace`; from the catalogue: `skill:kde-agent-workspace/use-chrome`).
It opens a Chrome window on {desktop_name} and creates the extension's tab group
inside it. Script: `{script}`.

Use the Chrome profile that matches the account the task is about (`kagent.py
chrome-profiles` lists them; `browser-window --profile <name|email>`). It is already
signed in, so don't sign in again in another profile. A profile without the Claude
in Chrome extension can't be driven: ask the user to install it there.

Managed by `kagent.py claude-md`; edit the plugin, not this block.
{MD_END}
"""


def cmd_claude_md(a):
    """Write (or remove) the Claude-in-Chrome directive in a CLAUDE.md, idempotently."""
    target = Path(a.file).expanduser()
    text = target.read_text() if target.exists() else ""
    if MD_BEGIN in text and MD_END in text:
        head, _, rest = text.partition(MD_BEGIN)
        _, _, tail = rest.partition(MD_END)
        text = head + "\0" + tail
    elif not a.remove:
        # Never append inside or after another tool's generated block (e.g. a
        # `<!-- habits-of-claude:begin -->` section rebuilt from source): go above it.
        lines = text.splitlines(keepends=True)
        at = next((i for i, l in enumerate(lines) if l.startswith("<!--") and l.rstrip().endswith(":begin -->")), None)
        if at is None:
            text = text.rstrip("\n") + ("\n\n" if text.strip() else "") + "\0\n"
        else:
            text = "".join(lines[:at]) + "\0\n\n" + "".join(lines[at:])
    if a.remove:
        new = text.replace("\0\n\n", "").replace("\0\n", "").replace("\0", "")
    else:
        name = (load_config().get("desktop_name") or DEFAULT_NAMES[0])
        new = text.replace("\0", chrome_directive(name).rstrip("\n"))
    changed = new != (target.read_text() if target.exists() else "")
    if changed and not a.dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new)
    out({"file": str(target), "changed": changed, "dry_run": a.dry_run, "removed": a.remove,
         "block": None if a.remove else chrome_directive(load_config().get("desktop_name") or DEFAULT_NAMES[0])})


CLAUDE_EXTENSION_ID = "fcoeoabgfenejglbffodgkkbkcdhcgfn"   # Claude in Chrome (Web Store id)


def chrome_profiles(user_data_dir):
    """Profiles from Chrome's `Local State`, with whether Claude in Chrome is installed in each.

    The extension is per profile: each profile that has it connects as a separate browser
    (its own deviceId in list_connected_browsers), and a profile without it cannot be driven.
    """
    root = Path(user_data_dir).expanduser()
    state = json.loads((root / "Local State").read_text())["profile"]
    return [{
        "dir": d,
        "name": v.get("name"),
        "email": v.get("user_name") or None,
        "claude_extension": (root / d / "Extensions" / CLAUDE_EXTENSION_ID).is_dir(),
        "last_used": d == state.get("last_used"),
    } for d, v in state.get("info_cache", {}).items()]


def resolve_chrome_profile(user_data_dir, wanted):
    """Match a profile by directory, display name or account email (case-insensitive)."""
    w = wanted.lower()
    profiles = chrome_profiles(user_data_dir)
    hits = [p for p in profiles if w in {p["dir"].lower(), (p["name"] or "").lower(), (p["email"] or "").lower()}]
    if len(hits) != 1:
        raise KagentError(f"profile {wanted!r} matched {len(hits)}; have "
                          + ", ".join(f"{p['dir']} ({p['name']}, {p['email']})" for p in profiles))
    return hits[0]


def cmd_chrome_profiles(a):
    out({"user_data_dir": a.user_data_dir, "profiles": chrome_profiles(a.user_data_dir)})


def cmd_browser_window(a):
    """Open a fresh browser window on the agent desktop for Claude in Chrome.

    The extension does not open a window of its own for a new tab group: it appends the
    group to whichever Chrome window was focused last. A freshly opened window is focused,
    so it keeps focus here (`previous_active` is returned) until the caller has created
    the tab group and calls `activate <previous_active>`.

    Without --profile Chrome opens the window in its last-used profile. With it, the
    window opens in that profile, which must have Claude in Chrome installed.
    """
    argv = [a.browser, "--new-window", "about:blank"]
    profile = None
    if a.profile:
        profile = resolve_chrome_profile(a.user_data_dir, a.profile)
        if not profile["claude_extension"]:
            raise KagentError(f"Chrome profile {profile['dir']} ({profile['name']}) has no Claude in Chrome "
                              "extension; the user must install it and connect it in that profile first")
        argv.insert(1, f"--profile-directory={profile['dir']}")
    d = agent_desktop()
    previous = active_window()
    before = {w["handle"] for w in kwin_windows()}
    proc, log = _spawn(argv)
    found, deadline = [], time.time() + a.timeout
    while time.time() < deadline and not found:
        time.sleep(0.3)
        found = _new_windows(before, proc, True, wm_class=a.wm_class or Path(a.browser).name)
    if not found:
        raise KagentError(f"no new {a.browser} window appeared within {a.timeout}s (log: {log})")
    win = move_window(found[0]["handle"], desktop_id=d["id"], output=a.output)
    out({
        "window": win,
        "profile": profile,
        "previous_active": previous,
        "agent_desktop": d,
        "next": "tabs_context_mcp {createIfEmpty: true} NOW, then: kagent.py activate <previous_active>",
    })


def cmd_move(a):
    did = agent_desktop()["id"] if a.to_agent else a.desktop
    out(move_window(a.handle, desktop_id=did, output=a.output,
                    on_all=True if a.all_desktops else (False if a.no_all_desktops else None)))


def cmd_outputs(a):
    out({"per_output_desktops": per_output_state(), "outputs": kwin_outputs()})


def cmd_bind_output(a):
    """Give the agent desktop its own output.

    Plasma >= 6.7 with per-output desktops: make the agent desktop current on that output only.
    Older Plasma: desktops always span every output, so the closest equivalent is moving the
    agent's windows onto that output and (with --pin) onto all desktops, i.e. a dedicated agent screen.
    """
    d = agent_desktop()
    po = per_output_state()
    outs = {o["name"]: o for o in kwin_outputs()}
    if a.output not in outs:
        raise KagentError(f"no output {a.output!r}; have {sorted(outs)}")
    result = {"per_output_desktops": po, "output": a.output, "agent_desktop": d}
    if po["supported"]:
        if not po["enabled"]:
            if not a.enable_per_output:
                raise KagentError("Plasma supports per-output desktops but they are off; rerun with "
                                  "--enable-per-output (sets kwinrc [Windows] PerOutputVirtualDesktops=true)")
            subprocess.run(["kwriteconfig6", "--file", "kwinrc", "--group", "Windows",
                            "--key", "PerOutputVirtualDesktops", "--type", "bool", "true"], check=True)
            _bus().get_object(KWIN, "/KWin").reconfigure(dbus_interface="org.kde.KWin")
            time.sleep(0.5)
            result["enabled_per_output"] = True
        result["set"] = run_kwin_script(JS_WINDOW + f"""
var o = findOutput({json.dumps(a.output)}), d = findDesk({json.dumps(d["id"])});
workspace.setCurrentDesktopForScreen(d, o);
return {{output: o.name, current: workspace.currentDesktopForScreen(o).id}};
""")
        result["mode"] = "per-output-desktop"
    else:
        wins = [w for w in kwin_windows() if d["id"] in w["desktops"] and not w["onAllDesktops"]]
        result["windows"] = [move_window(w["handle"], output=a.output, on_all=True if a.pin else None) for w in wins]
        result["mode"] = "dedicated-output-pinned" if a.pin else "windows-moved-to-output"
        result["note"] = ("Plasma < 6.7: virtual desktops span all outputs. Windows were moved to the output; "
                          + ("they are pinned to all desktops so the output always shows them."
                             if a.pin else "they are only visible while the agent desktop is current."))
    cfg = load_config()
    cfg["output"] = a.output
    save_config(cfg)
    out(result)


# ---------------------------------------------------------------- capture

def _python_hash():
    return hashlib.sha256(Path(os.path.realpath("/usr/bin/python3")).read_bytes()).hexdigest()


def cmd_setup_capture(a):
    """Install the KWin-authorised screenshot helper.

    org.kde.KWin.ScreenShot2 is restricted: KWin only serves processes whose executable is
    named by a .desktop file carrying X-KDE-DBUS-Restricted-Interfaces. Authorising
    /usr/bin/python3 would authorise every Python program, so we authorise a private copy
    of the interpreter that only this plugin runs.
    """
    HELPER_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(os.path.realpath("/usr/bin/python3"), HELPER_BIN)
    (HELPER_DIR / "python.sha256").write_text(_python_hash())
    HELPER_DESKTOP.parent.mkdir(parents=True, exist_ok=True)
    HELPER_DESKTOP.write_text(
        "[Desktop Entry]\nType=Application\nName=KDE Agent Workspace capture helper\n"
        f"Exec={HELPER_BIN}\nNoDisplay=true\n"
        "X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2\n")
    subprocess.run(["kbuildsycoca6"], capture_output=True)
    out({"helper": str(HELPER_BIN), "desktop_file": str(HELPER_DESKTOP)})


def cmd_remove_capture(a):
    HELPER_DESKTOP.unlink(missing_ok=True)
    shutil.rmtree(HELPER_DIR, ignore_errors=True)
    subprocess.run(["kbuildsycoca6"], capture_output=True)
    out({"removed": [str(HELPER_DESKTOP), str(HELPER_DIR)]})


def _png(path, width, height, stride, data):
    rows = b"".join(
        b"\x00" + bytes(_bgra_row_to_rgba(data[y * stride:y * stride + width * 4]))
        for y in range(height))

    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))


def _bgra_row_to_rgba(row):
    b = bytearray(row)
    b[0::4], b[2::4] = row[2::4], row[0::4]
    return b


def cmd_capture_raw(a):
    """Runs inside the authorised helper. Not for direct use."""
    import dbus
    from dbus.types import UnixFd
    obj = _bus().get_object(KWIN, "/org/kde/KWin/ScreenShot2")
    r, w = os.pipe()
    opts = {"include-decoration": True, "include-shadow": False, "native-resolution": True}
    try:
        if a.window:
            meta = obj.CaptureWindow(a.window, opts, UnixFd(w), dbus_interface="org.kde.KWin.ScreenShot2")
        else:
            meta = obj.CaptureScreen(a.screen, opts, UnixFd(w), dbus_interface="org.kde.KWin.ScreenShot2")
    except dbus.DBusException as e:
        os.close(w)
        raise KagentError(f"{e.get_dbus_name()}: {e.get_dbus_message()}")
    os.close(w)
    chunks = []
    while True:
        c = os.read(r, 1 << 20)
        if not c:
            break
        chunks.append(c)
    os.close(r)
    data = b"".join(chunks)
    width, height, stride = int(meta["width"]), int(meta["height"]), int(meta["stride"])
    _png(a.output, width, height, stride, data)
    out({"file": a.output, "width": width, "height": height})


def cmd_capture(a):
    if not (HELPER_BIN.exists() and HELPER_DESKTOP.exists()):
        raise KagentError("capture helper not installed — run `kagent.py setup-capture` (one-time)")
    stamp = HELPER_DIR / "python.sha256"
    if not stamp.exists() or stamp.read_text() != _python_hash():
        cmd_setup_capture(argparse.Namespace())   # interpreter upgraded; the private copy would load the wrong stdlib
    outfile = a.output or str(CACHE_DIR / f"capture-{time.strftime('%Y%m%d-%H%M%S')}.png")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    prev = None
    if a.peek:
        # Hidden-desktop windows get no Wayland frame callbacks, so they stop repainting and
        # CaptureWindow returns the last frame committed while visible. A brief switch refreshes it.
        d = agent_desktop()
        prev = current_desktop_id()
        if prev != d["id"]:
            vdm_set("current", d["id"])
            time.sleep(a.peek_ms / 1000)
    try:
        args = [str(HELPER_BIN), os.path.abspath(__file__), "capture-raw", "-o", outfile]
        args += ["--window", a.window] if a.window else ["--screen", a.screen or kwin_outputs()[0]["name"]]
        env = dict(os.environ, PYTHONHOME="/usr")
        r = subprocess.run(args, capture_output=True, text=True, env=env)
    finally:
        if prev and prev != current_desktop_id():
            vdm_set("current", prev)
    if r.returncode != 0:
        raise KagentError((r.stdout + r.stderr).strip())
    res = json.loads(r.stdout)
    res["peeked"] = bool(a.peek)
    res["fresh"] = bool(a.peek) or (a.window is None)
    out(res)


# ---------------------------------------------------------------- AT-SPI

def _atspi():
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi
    return Atspi


def _app_for(pid):
    Atspi = _atspi()
    desk = Atspi.get_desktop(0)
    pids = _descendants(pid) | {pid}
    for i in range(desk.get_child_count()):
        c = desk.get_child_at_index(i)
        if c and c.get_process_id() in pids:
            return c
    raise KagentError(f"pid {pid} is not on the AT-SPI bus — launch it via `kagent.py launch` "
                      "(sets QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1) or the app has no accessibility support")


def _walk(node, path=(), depth=0, max_depth=60):
    yield path, node
    if depth >= max_depth:
        return
    for i in range(node.get_child_count()):
        c = node.get_child_at_index(i)
        if c:
            yield from _walk(c, path + (i,), depth + 1, max_depth)


def _node_info(Atspi, path, n):
    ss = n.get_state_set()
    info = {"path": ".".join(map(str, path)), "role": n.get_role_name(), "name": n.get_name(),
            "description": n.get_description(),
            "showing": ss.contains(Atspi.StateType.SHOWING), "enabled": ss.contains(Atspi.StateType.ENABLED),
            "focused": ss.contains(Atspi.StateType.FOCUSED)}
    try:
        info["text"] = Atspi.Text.get_text(n, 0, -1)
    except Exception:
        pass
    try:
        ai = n.get_action_iface()
        if ai:
            info["actions"] = [ai.get_action_name(i) for i in range(ai.get_n_actions())]
    except Exception:
        pass
    return info


def _match(a, Atspi):
    app = _app_for(a.pid)
    nodes = []
    for path, n in _walk(app):
        if a.path is not None:
            if ".".join(map(str, path)) == a.path:
                return path, n
            continue
        if a.role and n.get_role_name() != a.role:
            continue
        if a.name is not None and a.name not in (n.get_name(), n.get_description()):
            continue
        if not a.include_hidden and not n.get_state_set().contains(Atspi.StateType.SHOWING):
            continue
        nodes.append((path, n))
    if not nodes:
        raise KagentError("no matching accessible element")
    if a.index >= len(nodes):
        raise KagentError(f"only {len(nodes)} matches")
    return nodes[a.index]


def cmd_a11y_tree(a):
    Atspi = _atspi()
    app = _app_for(a.pid)
    res = []
    for path, n in _walk(app, max_depth=a.depth):
        info = _node_info(Atspi, path, n)
        if a.showing_only and not info["showing"] and path:
            continue
        if a.interactive_only and not (info.get("actions") or "text" in info):
            continue
        res.append(info)
    out({"app": app.get_name(), "count": len(res), "nodes": res})


def cmd_a11y_click(a):
    Atspi = _atspi()
    path, n = _match(a, Atspi)
    ai = n.get_action_iface()
    if not ai:
        raise KagentError("element has no actions")
    names = [ai.get_action_name(i) for i in range(ai.get_n_actions())]
    idx = names.index(a.action) if a.action in names else 0
    ok = ai.do_action(idx)
    out({"clicked": _node_info(Atspi, path, n), "action": names[idx] if names else None, "ok": bool(ok)})


def cmd_a11y_set_text(a):
    Atspi = _atspi()
    path, n = _match(a, Atspi)
    ok = Atspi.EditableText.set_text_contents(n, a.text)
    out({"element": _node_info(Atspi, path, n), "ok": bool(ok)})


def cmd_a11y_read(a):
    Atspi = _atspi()
    path, n = _match(a, Atspi)
    out(_node_info(Atspi, path, n))


# ---------------------------------------------------------------- CLI

def main():
    p = argparse.ArgumentParser(prog="kagent.py", description=__doc__.splitlines()[0])
    s = p.add_subparsers(dest="cmd", required=True)

    s.add_parser("status", help="desktops, outputs, agent desktop, per-output support").set_defaults(f=cmd_status)

    c = s.add_parser("create", help="create (or adopt) the agent desktop")
    c.add_argument("--name", required=True, help='e.g. "Claude" or "AI Agents"')
    c.add_argument("--position", type=int, help="0-based position; default: last")
    c.set_defaults(f=cmd_create)

    c = s.add_parser("rename", help="rename the agent desktop")
    c.add_argument("--name", required=True)
    c.set_defaults(f=cmd_rename)

    s.add_parser("remove", help="remove the agent desktop (its windows move to a neighbour)").set_defaults(f=cmd_remove)
    s.add_parser("show", help="switch the view to the agent desktop").set_defaults(f=cmd_show)
    c = s.add_parser("switch", help="switch the view to a desktop id")
    c.add_argument("desktop_id")
    c.set_defaults(f=cmd_switch)

    c = s.add_parser("windows", help="windows on the agent desktop")
    c.add_argument("--all", action="store_true", help="every window, all desktops")
    c.set_defaults(f=cmd_windows)

    c = s.add_parser("launch", help="start an app and put its window(s) on the agent desktop")
    c.add_argument("--timeout", type=float, default=15)
    c.add_argument("--settle", type=float, default=0.7, help="seconds to wait for extra windows after the first")
    c.add_argument("--any-new-window", action="store_true", help="accept windows from non-child processes")
    c.add_argument("--output", help="also send the window(s) to this output")
    c.add_argument("--keep-focus", action="store_true", help="leave keyboard focus on the new window")
    c.add_argument("argv", nargs=argparse.REMAINDER, help="-- command [args...]")
    c.set_defaults(f=cmd_launch)

    c = s.add_parser("activate", help="give a window keyboard focus (switches the view if it is on another desktop)")
    c.add_argument("handle")
    c.set_defaults(f=cmd_activate)

    c = s.add_parser("browser-window", help="open a fresh browser window on the agent desktop for Claude in Chrome")
    c.add_argument("--browser", default="google-chrome")
    c.add_argument("--wm-class", help="KWin resourceClass of the browser; default: basename of --browser")
    c.add_argument("--output", help="also send the window to this output")
    c.add_argument("--timeout", type=float, default=10)
    c.add_argument("--profile", help="Chrome profile: directory, display name or account email (see chrome-profiles)")
    c.add_argument("--user-data-dir", default="~/.config/google-chrome")
    c.set_defaults(f=cmd_browser_window)

    c = s.add_parser("chrome-profiles", help="list Chrome profiles and whether Claude in Chrome is installed in each")
    c.add_argument("--user-data-dir", default="~/.config/google-chrome")
    c.set_defaults(f=cmd_chrome_profiles)

    c = s.add_parser("close", help="close a window by handle")
    c.add_argument("handle")
    c.set_defaults(f=cmd_close)

    c = s.add_parser("claude-md", help="write the Claude-in-Chrome agent-workspace directive into a CLAUDE.md")
    c.add_argument("--file", default="~/.claude/CLAUDE.md", help="default: user-level ~/.claude/CLAUDE.md")
    c.add_argument("--remove", action="store_true")
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(f=cmd_claude_md)

    c = s.add_parser("move", help="move a window by handle")
    c.add_argument("handle")
    g = c.add_mutually_exclusive_group()
    g.add_argument("--to-agent", action="store_true")
    g.add_argument("--desktop")
    c.add_argument("--output")
    c.add_argument("--all-desktops", action="store_true")
    c.add_argument("--no-all-desktops", action="store_true")
    c.set_defaults(f=cmd_move)

    s.add_parser("outputs", help="connected outputs and per-output desktop support").set_defaults(f=cmd_outputs)
    c = s.add_parser("bind-output", help="give the agent desktop its own output")
    c.add_argument("output", help="output name, e.g. HDMI-A-1 (see `outputs`)")
    c.add_argument("--enable-per-output", action="store_true", help="Plasma >= 6.7: turn the setting on if off")
    c.add_argument("--pin", action="store_true", help="Plasma < 6.7: pin agent windows to all desktops on that output")
    c.set_defaults(f=cmd_bind_output)

    s.add_parser("setup-capture", help="install the authorised screenshot helper").set_defaults(f=cmd_setup_capture)
    s.add_parser("remove-capture", help="uninstall the screenshot helper").set_defaults(f=cmd_remove_capture)
    c = s.add_parser("capture", help="PNG of a window (even on a hidden desktop) or an output")
    g = c.add_mutually_exclusive_group(required=True)
    g.add_argument("--window", help="window handle from `windows`/`launch`")
    g.add_argument("--screen", help="output name")
    c.add_argument("-o", "--output")
    c.add_argument("--peek", action="store_true", help="flash the agent desktop so the frame is current")
    c.add_argument("--peek-ms", type=int, default=400)
    c.set_defaults(f=cmd_capture)
    c = s.add_parser("capture-raw", help=argparse.SUPPRESS)
    c.add_argument("--window")
    c.add_argument("--screen")
    c.add_argument("-o", "--output", required=True)
    c.set_defaults(f=cmd_capture_raw)

    def a11y(name, fn, help_):
        c = s.add_parser(name, help=help_)
        c.add_argument("pid", type=int)
        c.add_argument("--name", help="match accessible name or description")
        c.add_argument("--role", help='e.g. "button", "text", "menu item"')
        c.add_argument("--path", help="exact node path from a11y-tree")
        c.add_argument("--index", type=int, default=0, help="which match, if several")
        c.add_argument("--include-hidden", action="store_true")
        c.set_defaults(f=fn)
        return c

    c = s.add_parser("a11y-tree", help="dump the app's accessibility tree")
    c.add_argument("pid", type=int)
    c.add_argument("--depth", type=int, default=60)
    c.add_argument("--showing-only", action="store_true")
    c.add_argument("--interactive-only", action="store_true")
    c.set_defaults(f=cmd_a11y_tree)
    a11y("a11y-click", cmd_a11y_click, "invoke an element's action (works on hidden desktops)").add_argument("--action")
    a11y("a11y-set-text", cmd_a11y_set_text, "replace the text of an editable element").add_argument("--text", required=True)
    a11y("a11y-read", cmd_a11y_read, "read one element (text, state, actions)")

    a = p.parse_args()
    if a.cmd == "launch":
        if a.argv and a.argv[0] == "--":
            a.argv = a.argv[1:]
        if not a.argv:
            p.error("launch needs a command after --")
    try:
        a.f(a)
    except KagentError as e:
        out({"error": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    main()
