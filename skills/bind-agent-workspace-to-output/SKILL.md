---
name: bind-agent-workspace-to-output
description: Bind the agent's KDE Plasma virtual desktop to a specific display output (e.g. a second monitor), or move agent windows onto an output, so the agent works on its own screen while the user keeps theirs. Uses per-output virtual desktops on Plasma 6.7+, and a dedicated-output fallback on older Plasma. Use when the user has more than one display and wants the agent's workspace on one of them.
---

# Bind the agent workspace to an output

```bash
KAGENT="${CLAUDE_PLUGIN_ROOT}/scripts/kagent.py"
"$KAGENT" outputs
```

Returns `per_output_desktops` (`plasma`, `supported`, `enabled`) and `outputs[]` (names like
`eDP-1` for a laptop panel, `HDMI-A-1`, `DP-2`). One output only → say binding needs a
second display and stop. An agent desktop must exist (`create-agent-workspace`).

Ask which output the agent gets if it isn't obvious. Usually it's the non-primary or
external one.

## Plasma ≥ 6.7 — real per-output desktops

Plasma 6.7 (June 2026, KWin MR !8602) added independent virtual desktops per output.
It is **off by default**: `kwinrc` `[Windows]` `PerOutputVirtualDesktops=true`, also
exposed in System Settings → Virtual Desktops.

```bash
"$KAGENT" bind-output HDMI-A-1                      # fails if the setting is off
"$KAGENT" bind-output HDMI-A-1 --enable-per-output  # turns it on, reconfigures KWin, then binds
```

Ask before `--enable-per-output`. It changes how desktop switching behaves on every
screen, not just the agent's. Binding makes the agent desktop current **on that output
only**; the user's other screens stay where they are. After this, agent windows on that
desktop are actually visible, so `capture` frames are fresh without `--peek`. The user
can also watch the agent work.

Per-output setup has not yet been exercised live by this plugin. Its first live run was
on 6.6, which lacks the feature. The calls used are
`workspace.setCurrentDesktopForScreen(desktop, output)` and
`workspace.currentDesktopForScreen(output)` from the 6.7 scripting API. If the output
shows a JS error, report it rather than working around it.

## Plasma < 6.7 — dedicated output

Before 6.7 a virtual desktop always spans every output. Switching desktops switches all
screens together. There is no way to bind a desktop to one screen. The closest equivalents:

```bash
"$KAGENT" bind-output HDMI-A-1          # move agent windows onto that output (visible only while the agent desktop is current)
"$KAGENT" bind-output HDMI-A-1 --pin    # also pin them to all desktops: that screen always shows the agent's windows
```

`--pin` effectively makes the monitor the agent's workspace whatever desktop is current.
The trade-off: those windows also overlay that monitor on the user's desktops. Explain
the trade-off and let the user choose.

## Moving individual windows

```bash
"$KAGENT" windows                          # handles
"$KAGENT" move '<handle>' --output DP-2
"$KAGENT" move '<handle>' --to-agent --output DP-2
"$KAGENT" launch --output DP-2 -- myapp    # launch straight onto that output
```

The chosen output is saved as `output` in `~/.config/kde-agent-workspace/config.json`.
Re-run `bind-output` after reconnecting a monitor. Output names stay stable per
connector, but bindings do not survive the output disappearing.
