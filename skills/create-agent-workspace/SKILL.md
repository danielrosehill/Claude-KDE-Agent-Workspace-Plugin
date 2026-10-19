---
name: create-agent-workspace
description: Create a dedicated KDE Plasma virtual desktop for AI agents to work on, named "Claude" or "AI Agents" (the user's choice), and remember it as the agent desktop. Idempotent — adopts an existing desktop of that name. Also renames or removes it. Use when the user wants Claude to have its own workspace, or before testing apps in an agent workspace when none exists.
---

# Create the agent workspace

```bash
KAGENT="${CLAUDE_PLUGIN_ROOT}/scripts/kagent.py"
"$KAGENT" status        # see what exists first
```

## 1. Pick the name

If `status` already shows an `agent_desktop`, there is nothing to create. Say so and stop.

Otherwise ask the user which name they want, offering exactly the two conventions plus free text:

- **Claude** — this agent's own space
- **AI Agents** — shared by any agent tools the user runs

Do not pick for them. The name is the visible label in the pager and Overview.

## 2. Create

```bash
"$KAGENT" create --name "Claude"          # appended as the last desktop
"$KAGENT" create --name "AI Agents" --position 0   # or at a chosen position
```

Returns `{"created": true|false, "desktop": {...}, "config_file": ...}`. `created: false`
means a desktop with that name already existed and was adopted. The choice is stored
in `~/.config/kde-agent-workspace/config.json` (`desktop_name`, `desktop_id`), and every
other command resolves the agent desktop from it.

Creating a desktop does **not** switch the user's view. Tell the user where it is
(position N in the pager, Meta+Ctrl+Left/Right default navigation, or Overview with Meta+W).

## 3. Optional: capture helper

For screenshots of agent windows later, install the helper once:

```bash
"$KAGENT" setup-capture
```

It copies the system Python interpreter to
`~/.local/share/kde-agent-workspace/bin/kagent-capture`. It also writes
`~/.local/share/applications/kagent-capture.desktop`, which declares
`X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2`. KWin only serves its
screenshot API to executables declared this way. Tell the user this in one sentence
before running it; `remove-capture` undoes it.

## Rename / remove

```bash
"$KAGENT" rename --name "AI Agents"
"$KAGENT" remove      # KWin moves its windows to a neighbouring desktop
```

Confirm with the user before `remove`.

## Raw D-Bus (if the script is unavailable)

```bash
qdbus6 org.kde.KWin /VirtualDesktopManager createDesktop <position> "Claude"
qdbus6 org.kde.KWin /VirtualDesktopManager setDesktopName <id> "AI Agents"
qdbus6 org.kde.KWin /VirtualDesktopManager removeDesktop <id>
```
