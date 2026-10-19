# Findings: driving apps on a hidden KDE Plasma desktop

Verified live on **2026-10-19**: Plasma 6.6.6 / KWin 6.6.6 / Wayland, Ubuntu 26.04.1,
single 1920×1080 output (`eDP-1`), Python 3.14.4, python3-dbus 1.4.0,
gir1.2-atspi-2.0 2.60.4. "Verified" means run and observed on that machine.
"Inferred" means read from source or docs but not run.

## Virtual desktop D-Bus API — properties, not methods (verified)

`org.kde.KWin` `/VirtualDesktopManager`, interface `org.kde.KWin.VirtualDesktopManager`:

| Member | Kind | Notes |
| --- | --- | --- |
| `desktops` | property, `a(uss)` | `(position, id, name)`; position is 0-based |
| `current` | property, `s`, readwrite | Set it to switch desktops |
| `count`, `rows` | property, `u` | |
| `navigationWrappingAround` | property, `b` | |
| `createDesktop(u position, s name)` | method | |
| `removeDesktop(s id)` | method | |
| `setDesktopName(s id, s name)` | method | |

`qdbus6 org.kde.KWin /VirtualDesktopManager desktopIds` / `count` / `setCurrent` do not
exist as methods. Use `org.freedesktop.DBus.Properties.Get/Set`.

## KWin scripting from the shell (verified)

- `org.kde.kwin.Scripting.loadScript` is **overloaded** `(s)` and `(ss)`. `qdbus6` resolves
  it; dbus-python's introspecting proxy picks `(s)` and raises *"Fewer items found in D-Bus
  signature than in Python arguments"*. Call with an explicit `"ss"` signature.
- Flow: `loadScript(path, pluginName)` → id → `/Scripting/Script<id>` `org.kde.kwin.Script.run`
  → `unloadScript(pluginName)`. Use a fresh plugin name per run.
- `print()` output lands in the **user journal** as `js: <text>`. No D-Bus return path
  exists, so tag output with a nonce and read `journalctl --user --since @<epoch> -o cat`.
- Working 6.6 API: `workspace.windowList()`, `w.internalId` (UUID with braces),
  `w.pid`, `w.resourceClass`, `w.desktops` (assignable array of VirtualDesktop),
  `w.onAllDesktops`, `w.output`, `workspace.desktops`, `workspace.screens`,
  `workspace.sendClientToScreen(w, output)`.
- Assigning `w.desktops = [d]` moves a window to a non-current desktop without changing
  the user's current desktop.

## Screenshots: ScreenShot2 is restricted (verified)

- `org.kde.KWin.ScreenShot2.CaptureWindow(handle, options, fd)` from plain `python3` →
  `org.kde.KWin.ScreenShot2.Error.NoAuthorized: The process is not authorized to take a screenshot`.
- KWin authorises the calling executable if a `.desktop` file names it in `Exec=` and carries
  `X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2`. A file in
  `~/.local/share/applications/` plus `kbuildsycoca6` is enough. No root and no relogin.
- Authorising `/usr/bin/python3` would authorise every Python program. Instead, copy the interpreter to a
  private path and authorise that. The copy needs `PYTHONHOME=/usr` to find its stdlib.
  It breaks on a Python minor upgrade, so `kagent.py capture` re-copies when the
  interpreter's hash changes.
- The handle is the KWin `internalId` UUID **with braces**.
- The pipe receives raw pixels; the reply map gives `width`, `height`, `stride`,
  `format` (`6` = QImage::Format_ARGB32, little-endian BGRA in memory), `scale`.

## Hidden desktops: input works, pixels go stale (verified)

- `CaptureWindow` on a window that sits on a non-current desktop **succeeds**.
- But the image is the last frame committed while the window was visible. After
  clicking 7 × 6 = via AT-SPI, the capture still showed an empty display while AT-SPI
  read `42`. Cause (inferred, consistent with Wayland semantics): hidden surfaces get no
  `wl_surface.frame` callbacks, so Qt stops rendering.
- Switching to the desktop for 400 ms and capturing gives a correct frame (`42` shown).
  `capture --peek` does this.
- Plasma ≥ 6.7 per-output desktops should remove the need when the agent desktop is shown
  on its own monitor (inferred, not run).

## AT-SPI (verified)

- Qt apps are **absent** from the AT-SPI registry unless launched with
  `QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1`. kcalc launched normally did not appear;
  relaunched with it, it did. `org.gnome.desktop.interface toolkit-accessibility` was
  `false`. GTK apps (Chrome, gnome-text-editor) were registered without help.
- `Action.do_action(0)` on a button works while the window is on a hidden desktop.
- KCalc keeps hidden duplicate buttons with names like `7`. The visible ones are named
  `Seven`, `Multiply`, `Equals`. Filter on `StateType.SHOWING`.
- `Atspi.Text.get_text(node, 0, -1)` is the working call. `node.get_text(...)` is a deprecated
  one-argument API.
- Konsole exposes its visible terminal buffer as text. `konsole --separate --hold -e …`
  output is readable without a screenshot.

## Per-output virtual desktops (inferred from source, 2026-10-19)

- Not in Plasma 6.6. `libkwin.so.6.6.6` has no such config string.
- Added by KWin MR !8602 *"virtualdesktops: Add per-output desktops"*, merged 2026-04-13,
  released in Plasma 6.7 (June 2026). Opt-in, Wayland-only.
- Config: `kwinrc` group `[Windows]`, key `PerOutputVirtualDesktops` (bool, default false),
  from `src/kwin.kcfg` on master.
- Scripting: `workspace.currentDesktopForScreen(output)`,
  `workspace.setCurrentDesktopForScreen(desktop, output)`, and
  `currentDesktopChanged(previous, current, output)`.
- The D-Bus `current` property reports the desktop of the **active** output.

## Focus follows a moved window (verified)

- A window launched on the user's desktop is active, and stays active after
  `w.desktops = [agentDesktop]` moves it. The view does not switch, so the user's
  keystrokes go to a window they cannot see. Observed: a stray `a` in the agent Chrome
  window's address bar. `launch` now records `workspace.activeWindow` first and restores
  it afterwards.
- Setting `workspace.activeWindow = w` for a window on another desktop **switches the
  current desktop** to it. Activation cannot be used to focus an agent window silently.
- `--any-new-window` once took a KDE portal "Open File" dialog
  (`org.freedesktop.impl.portal.desktop.kde`) that the user had just opened from Chrome.
  Moving it to the agent desktop moved its parent Chrome window too, because KWin keeps
  transient groups together. New windows whose `transientFor` existed before the launch
  are now never taken. `winInfo` exposes `transientFor`.
- Windows on a hidden desktop ignore `frameGeometry` and maximize changes: the
  geometry read back unchanged with `maximizeMode` still `3`.

## Claude in Chrome (verified, Chrome 155.0.8059.79, extension as of 2026-10-19)

- `tabs_context_mcp {createIfEmpty: true}` says it "creates a new Window". It does
  not. KWin's `windowList()` and `stackingOrder` gained no window, and the
  probe tab's title never appeared in any window caption. The group is added to the
  **last-focused Chrome window** as a background tab. Closing the group's last tab left the
  window count unchanged.
- Proof of placement: launch `google-chrome --new-window about:blank` (it gets focus),
  create the group, then peek-capture that window. The tab strip showed
  `about:blank` + the "Claude" group. When focus had gone back to the user's Chrome
  first, the group landed in the user's window and the agent window showed only
  `about:blank`.
- With the agent window on a hidden desktop and **not** focused: navigate, click, scroll,
  `javascript_tool` and `computer screenshot` all worked, and screenshots were current.
  `document.visibilityState` reported `visible` and `hasFocus()` `true`. The first
  screenshot after group creation timed out once (`CDP sendCommand
  "Page.captureScreenshot" timed out after 30000ms`). The retry succeeded.
- Chrome on Wayland reports `outerWidth/outerHeight` equal to the viewport, which does
  not identify the window. The tab strip has no AT-SPI exposure by default: the
  `a11y-tree` of the Chrome pid showed only 6 frames. A peek capture is the working check.
- All Chrome windows share one process (pid of `/opt/google/chrome/chrome`). Close the
  agent window with KWin `w.closeWindow()` (`kagent.py close`), never `kill`.
