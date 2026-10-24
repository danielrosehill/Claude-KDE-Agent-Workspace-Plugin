---
name: use-chrome
description: Use Claude in Chrome inside the agent's own KDE virtual desktop instead of the user's active workspace. Opens a Chrome window on the agent desktop, makes the Claude in Chrome tab group land in it, and hands keyboard focus back, so browsing, clicking and screenshots happen out of the user's sight. Run it before the first mcp__claude-in-chrome__* call of any browser task. Also installs the CLAUDE.md directive that makes this the default.
---

# Use Claude in Chrome in the agent workspace

The user's current desktop is their private workspace. Browser work goes in a Chrome
window on the agent desktop (**Claude** or **AI Agents**, see `create-agent-workspace`).
The tab group lands in whichever Chrome window **last had focus**, so the steps below
make that the agent window. Why, and the raw fallback without the script:
`references/why-and-fallback.md`.

```bash
KAGENT="${CLAUDE_PLUGIN_ROOT}/scripts/kagent.py"   # read from the catalogue? use the clone's scripts/kagent.py
"$KAGENT" status        # need an agent_desktop; none → run create-agent-workspace first
```

## 0. Pick the Chrome profile

```bash
"$KAGENT" chrome-profiles      # dir, name, account email, claude_extension, last_used
```

- The account in the task (e.g. `daniel@dsrholdings.cloud`, "my work browser",
  "the business profile") picks the profile. With no hint, use the last-used one.
  Drive **that profile**; don't sign in again in another one.
- **Claude in Chrome is per profile**: each profile with it is its own entry in
  `list_connected_browsers`, with its own `deviceId`. A profile with
  `claude_extension: false` cannot be driven. Stop and ask the user to install the
  extension in that profile and connect it there. Don't fall back to another
  profile's window.
- With more than one browser connected, the tab group goes to the **selected**
  browser. Before step 1, `select_browser` the profile's `deviceId`. If you can't tell
  which `deviceId` is which profile, ask with AskUserQuestion, or use `switch_browser`
  and let them click Connect in the right one. Never guess.

## 1. Clear any existing group

`tabs_context_mcp` (no `createIfEmpty`). If it lists tabs you opened earlier in this
session, close them with `tabs_close_mcp`; the group disappears with its last tab.
Otherwise `createIfEmpty` in step 3 is a no-op and you keep working wherever the old
group lives. Do not close tabs you did not open.

## 2. Open the agent window

```bash
"$KAGENT" browser-window --profile 'DSR Holdings'   # omit --profile for the last-used profile
                                                   # --browser chromium / --wm-class … for other Chromium builds
```

`--profile '<name|email|dir>'` refuses a profile without the extension. Without the flag, Chrome opens
the window in its **last-used** profile, which may not be the one whose extension
you selected. Returns `window.handle` (the agent window, on the agent desktop and
focused) and `previous_active` (the user's window). The window flashes on the user's
screen for a few hundred ms before it moves.

## 3. Create the group immediately, then return focus

Back to back, with nothing in between — until `activate` runs, the user's keystrokes
land in the hidden window:

```
tabs_context_mcp {createIfEmpty: true}      → note the tabId
```
```bash
"$KAGENT" activate '<previous_active>'
```

## 4. Check where the group landed (once per session)

```bash
"$KAGENT" capture --window '<window.handle>' --peek -o /tmp/kagent-chrome.png
```

Read the image: the tab strip should show `about:blank` and a group chip labelled
**Claude**. Without `--peek` the frame is stale and shows no group (the peek flashes
the agent desktop for ~0.4 s). No group means the user focused another Chrome window
between steps 2 and 3: close the group's tabs and repeat steps 2–3.

## 5. Work

Use the Claude in Chrome tools with that `tabId`; `tabs_create_mcp` adds tabs to the
same group and window.

- The first `screenshot` after the group is created may time out ("CDP sendCommand
  Page.captureScreenshot timed out"). Retry once.
- Do not `show` the agent desktop or `activate` the window to "help" it. Neither is
  needed, and both take over the user's screen.

## 6. Clean up

Close the tabs you opened (`tabs_close_mcp`), then `"$KAGENT" close '<window.handle>'`.
Do not use `kill`: Chrome runs every window in one process, so that would close the
user's browser.

## Directive in CLAUDE.md

To make this the default in every session (`"$KAGENT" claude-md`), read
`references/claude-md-directive.md` first.
