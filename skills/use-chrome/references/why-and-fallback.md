# Why `use-chrome` needs a procedure, and the raw fallback

Read this when a step misbehaves (the group lands in the wrong window, the view
switches desktops) or when `kagent.py` is unavailable.

## Why (verified 2026-10-19, Chrome 155, Plasma 6.6.6 Wayland)

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
- `document.visibilityState` reads `visible` even though the desktop is hidden.
- Seen in testing: until `activate` returns focus (step 3), the user's keystrokes land
  in the hidden window — a stray letter typed into the agent window's address bar.

## Profiles: why drive the existing one

Each Chrome profile is signed into its own Google account and holds its own console
sessions. Signing in again in another profile is often blocked anyway: Workspace orgs
ask for a passkey re-verification, which the agent cannot complete. Display names in
`list_connected_browsers` are whatever the user typed when connecting ("Browser 1" by
default), so ask them to name each one after its profile.

## Raw fallback (script unavailable)

```bash
google-chrome --new-window about:blank &      # then find its handle and move it:
# KWin script: w.desktops = [agentDesktop]  (see ../../../reference/findings.md)
```
