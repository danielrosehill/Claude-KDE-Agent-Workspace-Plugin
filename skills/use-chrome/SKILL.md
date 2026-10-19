---
name: use-chrome
description: Use Claude in Chrome inside the agent's own KDE virtual desktop instead of the user's active workspace. Opens a Chrome window on the agent desktop, makes the Claude in Chrome tab group land in it, and hands keyboard focus back, so browsing, clicking and screenshots happen out of the user's sight. Run it before the first mcp__claude-in-chrome__* call of any browser task. Also installs the CLAUDE.md directive that makes this the default.
---

# Use Claude in Chrome in the agent workspace

The user's current desktop is their private workspace. Browser work goes in a Chrome
window on the agent desktop (**Claude** or **AI Agents**, see `create-agent-workspace`).

```bash
KAGENT="${CLAUDE_PLUGIN_ROOT}/scripts/kagent.py"   # read from the catalogue? use the clone's scripts/kagent.py
"$KAGENT" status        # need an agent_desktop; none → run create-agent-workspace first
```

## Why this needs a procedure (verified 2026-10-19, Chrome 155, Plasma 6.6.6 Wayland)

- `tabs_context_mcp {createIfEmpty: true}` does **not** open a window of its own,
  whatever its description says. It appends the "Claude" tab group to the Chrome window
  that **last had focus**. With nothing done first, that is the user's window.
- A new tab group can only be steered by deciding which Chrome window has focus at the
  moment it is created. Once created, it stays in that window.
- Activating a window that sits on another desktop makes KWin switch the view there. A
  *freshly opened* window, though, keeps focus after being moved off-screen, without
  switching the view. `browser-window` relies on that.
- In that window, everything works with the agent desktop hidden: navigate, click,
  type, scroll, `read_page`, `javascript_tool` and `computer screenshot`. The extension
  renders through CDP, so Wayland's stale-frame problem (see
  `test-app-in-agent-workspace`) does not apply.

## 1. Clear any existing group

```
tabs_context_mcp            (no createIfEmpty)
```

If it lists tabs you opened earlier in this session, close them with `tabs_close_mcp`.
The group disappears with its last tab. Otherwise `createIfEmpty` in step 3 is a no-op
and you keep working wherever the old group lives. Do not close tabs you did not open.

## 2. Open the agent window

```bash
"$KAGENT" browser-window          # --browser chromium / --wm-class … for other Chromium builds
```

Returns `window.handle` (the agent's Chrome window, now on the agent desktop and focused)
and `previous_active` (the user's window that had focus). The window flashes on the
user's screen for a few hundred ms before it moves.

## 3. Create the group immediately, then return focus

Do these back to back, with nothing in between:

```
tabs_context_mcp {createIfEmpty: true}      → note the tabId
```
```bash
"$KAGENT" activate '<previous_active>'      # user's typing goes back to their window
```

Until `activate` runs, the user's keystrokes land in the hidden window. Seen in testing:
a stray letter typed into the agent window's address bar. Keep the gap short.

## 4. Check where the group landed (once per session)

```bash
"$KAGENT" capture --window '<window.handle>' --peek -o /tmp/kagent-chrome.png
```

Read the image. The tab strip should show `about:blank` followed by a group chip labelled
**Claude**. Without `--peek` the frame is stale and shows no group. The peek flashes the
agent desktop for ~0.4 s.

If the group is not there, the user focused another Chrome window between steps 2 and 3.
Close the group's tabs and repeat steps 2–3.

## 5. Work

Use the Claude in Chrome tools as usual with that `tabId`. `tabs_create_mcp` adds tabs to
the same group, in the same window.

- The first `screenshot` after the group is created may time out ("CDP sendCommand
  Page.captureScreenshot timed out"). Retry once. In testing the retry and every later
  capture succeeded.
- `document.visibilityState` reads `visible` even though the desktop is hidden.
- Do not `show` the agent desktop or `activate` the window to "help" it. Neither is
  needed, and both take over the user's screen.

## 6. Clean up

Close the tabs you opened (`tabs_close_mcp`). Then close the agent window:

```bash
"$KAGENT" close '<window.handle>'
```

Do not use `kill`: Chrome runs every window in one process, so that would close the
user's browser.

## Directive in CLAUDE.md

To make this the default in every session, write the directive into a CLAUDE.md:

```bash
"$KAGENT" claude-md                       # user-level ~/.claude/CLAUDE.md (default)
"$KAGENT" claude-md --file ~/CLAUDE.md    # or a home-directory CLAUDE.md
"$KAGENT" claude-md --dry-run             # show the block without writing
"$KAGENT" claude-md --remove
```

It writes one block between `<!-- kde-agent-workspace:chrome:begin/end -->` markers.
Re-running updates the block in place. If the file already holds another tool's
generated `<!-- …:begin -->` block, the new block goes **above** it, so a rebuild of
that block does not erase it. The block names the agent desktop from
`~/.config/kde-agent-workspace/config.json`. After renaming the desktop, re-run it.
Tell the user which file you changed.

## Raw fallback (script unavailable)

```bash
google-chrome --new-window about:blank &      # then find its handle and move it:
# KWin script: w.desktops = [agentDesktop]  (see reference/findings.md)
```
