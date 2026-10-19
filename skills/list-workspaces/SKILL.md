---
name: list-workspaces
description: Show the user's KDE Plasma virtual desktops ("workspaces") — names, order, which is current, how many windows each holds, the connected outputs, whether an agent desktop already exists, and whether this Plasma version supports per-output desktops. Use when the user asks what workspaces/virtual desktops they have, before creating an agent desktop, or before any other skill in this plugin.
---

# List workspaces

KDE calls them **virtual desktops**; users often say "workspaces". Same thing.

## Run

```bash
KAGENT="${CLAUDE_PLUGIN_ROOT}/scripts/kagent.py"
"$KAGENT" status
```

If `CLAUDE_PLUGIN_ROOT` is unset (skill loaded outside an installed plugin), use the
`scripts/kagent.py` from a clone of
<https://github.com/danielrosehill/Claude-KDE-Agent-Workspace-Plugin>.

The script needs `/usr/bin/python3` with `python3-dbus`, `python3-gi` and
`gir1.2-atspi-2.0` — all present on a stock Kubuntu / Ubuntu-with-Plasma install. It
calls `/usr/bin/python3` through its shebang; do not run it inside a venv.

## Read the output

| Field | Meaning |
| --- | --- |
| `desktops[]` | `position` (0-based), `id` (UUID — the stable key), `name`, `current`, `windows` (count incl. sticky windows), `agent` |
| `agent_desktop` | The desktop this plugin treats as the agent's, or `null` if none yet. Resolved from `~/.config/kde-agent-workspace/config.json`, else by the name `Claude` or `AI Agents` |
| `outputs[]` | Connected displays (`eDP-1`, `HDMI-A-1`, `DP-2`…), geometry, which is active |
| `per_output_desktops` | `supported` is true on Plasma ≥ 6.7; `enabled` reflects `kwinrc [Windows] PerOutputVirtualDesktops` |
| `capture_helper_installed` | Whether `setup-capture` has been run (needed for screenshots) |

Report it to the user as a short table of desktops plus one line on outputs, then
say what is missing for the agent workflow (no agent desktop yet → offer
`create-agent-workspace`; second monitor present → mention
`bind-agent-workspace-to-output`).

## Manual equivalent

`desktops` and `current` are D-Bus **properties**, not methods:

```bash
qdbus6 --literal org.kde.KWin /VirtualDesktopManager \
  org.freedesktop.DBus.Properties.Get org.kde.KWin.VirtualDesktopManager desktops
```

Persistent copy: `~/.config/kwinrc`, group `[Desktops]` (`Id_N`, `Name_N`, `Number`, `Rows`).
`Name_N` is omitted for desktops still carrying the default "Desktop N" name.
