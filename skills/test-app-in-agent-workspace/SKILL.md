---
name: test-app-in-agent-workspace
description: Run, test and troubleshoot a real GUI or terminal application on Ubuntu/KDE Plasma inside the agent's own virtual desktop, so Claude can operate it without taking over the user's screen — launch it there, drive it via AT-SPI accessibility (clicks, text entry, reading values), capture window screenshots, and read its logs. Use when Claude needs to verify an app actually works, reproduce a GUI bug, or test a desktop build on the user's machine.
---

# Test an app in the agent workspace

The point: the user keeps working on their desktop while Claude opens, pokes and
inspects an app on its own. Everything below works **without switching the user's
view**, except where marked.

```bash
KAGENT="${CLAUDE_PLUGIN_ROOT}/scripts/kagent.py"
"$KAGENT" status
```

No `agent_desktop` → run the `create-agent-workspace` skill first. For screenshots,
`capture_helper_installed` must be true (`"$KAGENT" setup-capture`, one-time).

## What works where (verified Plasma 6.6.6 Wayland, 2026-10-19)

| Need | Mechanism | On a hidden desktop? |
| --- | --- | --- |
| Put a window on the agent desktop | KWin scripting (`window.desktops = [d]`) | Yes |
| Click buttons, menu items, toggles | AT-SPI `do_action` | **Yes** |
| Type into a text field | AT-SPI `EditableText.set_text_contents` | **Yes** |
| Read labels, field values, terminal text | AT-SPI `Text` | **Yes** — preferred over screenshots |
| Screenshot a window | KWin `ScreenShot2.CaptureWindow` | Yes, but **stale** — see below |
| Up-to-date screenshot | `capture --peek` | Flashes the agent desktop for ~0.4 s |
| Keystrokes / pointer (ydotool) | Goes to the focused window only | No — needs `show` |

**Stale frames:** Wayland stops sending frame callbacks to surfaces that aren't visible,
so an app on a hidden desktop stops repainting. `CaptureWindow` then returns the last
frame the app drew while it was visible. That is usually the pre-move first frame. Use
AT-SPI reads for state, and `--peek` when pixels matter. Warn the user once that peeks
flash their screen.

## 1. Launch

```bash
"$KAGENT" launch -- <command> [args...]
# e.g.
"$KAGENT" launch -- kcalc
"$KAGENT" launch -- ./build/myapp --debug
"$KAGENT" launch -- konsole --separate --hold -e bash -c 'my-cli --flag; echo EXIT=$?'
```

Returns `pid`, `log` (stdout+stderr of the app), and `windows[]` with each window's
`handle`. The handle is KWin's internal UUID, used by `capture`/`move`. The window
appears briefly on the user's desktop and is moved within a few hundred ms. The user's
current desktop is not changed. A new window takes keyboard focus and keeps it after the
move, so `launch` hands focus back to the window the user had (`focus_returned_to`).
Pass `--keep-focus` only when the app must stay focused.

`launch` sets `QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1` and unsets `NO_AT_BRIDGE`. Without
the first, Qt/KDE apps never register on the AT-SPI bus and cannot be driven.

If `windows` is empty, read the `note`:
- Single-instance or D-Bus-activated apps (Dolphin, Chrome, an already-running Konsole
  without `--separate`) open their window from another process. Retry with `--any-new-window`.
  Ask the user to keep their hands off while it runs: any window they open in that span
  gets taken too. Dialogs transient for an already-open window are always skipped.
  Moving one drags its parent along, and on 2026-10-19 that took the user's Chrome
  window together with its Open File portal.
- Browsers: use `browser-window`, which matches on window class.
- Slow start → `--timeout 40`.
- `exited` non-null → it crashed or is CLI-only; read `log`.

**Terminal / CLI programs:** a plain CLI needs no desktop. Run it with Bash directly.
Use the agent desktop for TUIs or when the terminal behaviour itself is under test.
Launch them in `konsole --separate --hold -e …` and read the screen text with
`a11y-tree <pid> --showing-only`. Konsole exposes its visible buffer as a `terminal`/`text` node.

## 2. Inspect and drive

```bash
"$KAGENT" a11y-tree <pid> --showing-only --interactive-only   # what can be clicked/typed
"$KAGENT" a11y-click <pid> --name "Seven"                    # by accessible name or description
"$KAGENT" a11y-click <pid> --role "menu item" --name "Quit"
"$KAGENT" a11y-click <pid> --path 0.0.3.12                   # exact node from the tree
"$KAGENT" a11y-set-text <pid> --role text --index 0 --text "hello"
"$KAGENT" a11y-read <pid> --role text                        # value of the first visible text node
```

Matching skips non-showing elements unless `--include-hidden`. Apps often keep hidden
duplicates; KCalc has hidden "7" buttons and visible ones named "Seven". When a name
fails, dump the tree and match on what is actually there; don't guess.

Accessible names are not visible labels. Buttons drawn as "7" or "=" may be exposed as
"Seven"/"Equals".

## 3. Look at it

```bash
"$KAGENT" windows                                   # agent-desktop windows + handles
"$KAGENT" capture --window '<handle>' --peek -o /path/shot.png
```

Then Read the PNG. Omit `--peek` only when a stale frame is acceptable (e.g. checking the
window opened at all). `capture --screen <output>` grabs a whole output; that shows the
*user's* current desktop unless the agent desktop is current there.

## 4. When keyboard/pointer input is unavoidable

Some widgets (canvases, games, custom-drawn controls) expose nothing to AT-SPI. Then:

```bash
"$KAGENT" show            # switches the view to the agent desktop; prints `previous`
# ydotool / kdotool / etc. against the focused window
"$KAGENT" switch <previous-id>
```

Ask the user before `show`: it takes over their screen until switched back. On a
second monitor with Plasma ≥ 6.7, `bind-agent-workspace-to-output` avoids this entirely.

## 5. Troubleshooting checklist

1. `log` file from `launch` — crashes, Qt warnings, missing libraries.
2. `journalctl --user --since "-5min" | grep -i <app>` — portal, D-Bus activation, KWin messages.
3. `coredumpctl list <binary>` then `coredumpctl info <pid>` for crashes.
4. Wayland vs XWayland: `windows` shows the class; force `QT_QPA_PLATFORM=xcb` /
   `GDK_BACKEND=x11` via `launch -- env QT_QPA_PLATFORM=xcb app` to compare.
5. Missing from AT-SPI: GTK4 and Qt6 support it. Electron needs
   `--force-renderer-accessibility`. Flutter and some games have no tree; fall back to step 4.

## 6. Clean up

Close what you opened: `kill <pid>` (or `a11y-click` the app's Quit). Leave the agent
desktop in place. It is the user's, not per-task. Report what you tested, what you
saw (attach the capture), and anything you could not drive.
