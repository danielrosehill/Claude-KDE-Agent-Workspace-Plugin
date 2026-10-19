# KDE Agent Workspace

![Plasma 6 Wayland](https://img.shields.io/badge/Plasma-6%20(Wayland)-1d99f3)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

A Claude Code plugin that gives the agent **its own KDE Plasma virtual desktop**. Claude
can launch, operate and inspect real applications there while you keep working on
yours.

Virtual desktops already exist to separate contexts. This plugin uses one to separate
the human from the agent.

## Skills

| Skill | What it does |
| --- | --- |
| `list-workspaces` | Your virtual desktops, outputs, which desktop is the agent's, and whether your Plasma supports per-output desktops |
| `create-agent-workspace` | Create (or adopt) a desktop called **Claude** or **AI Agents**, your choice; rename or remove it |
| `test-app-in-agent-workspace` | Launch a GUI or terminal app on the agent desktop, drive it through AT-SPI, screenshot it, read its logs, troubleshoot |
| `bind-agent-workspace-to-output` | Put the agent desktop on its own monitor: real per-output desktops on Plasma ≥ 6.7, a dedicated-output fallback before that |

All of them call one script, `scripts/kagent.py`, which prints JSON:

```
status | create | rename | remove | show | switch | windows | launch | move
outputs | bind-output | setup-capture | remove-capture | capture
a11y-tree | a11y-click | a11y-set-text | a11y-read
```

## How it works without taking over your screen

| Step | Mechanism | Needs the agent desktop visible? |
| --- | --- | --- |
| Move windows between desktops/outputs | KWin scripting via D-Bus | No |
| Click, type, read values | AT-SPI accessibility | No |
| Screenshot a window | KWin `ScreenShot2.CaptureWindow` | No, but the frame is stale. `--peek` flashes the agent desktop for ~0.4 s to refresh it |
| Raw keyboard/pointer | ydotool etc. | Yes |

Hidden windows stop repainting on Wayland. State checks therefore read the
accessibility tree, and screenshots peek only when the pixels matter. Details,
error strings and dates: [`reference/findings.md`](reference/findings.md).

## Requirements

- KDE Plasma 6 on **Wayland** (verified on 6.6.6, Ubuntu 26.04)
- `/usr/bin/python3` with `python3-dbus`, `python3-gi`, `gir1.2-atspi-2.0` (stock on Kubuntu)
- `qdbus6`, `kreadconfig6`/`kwriteconfig6`, `kbuildsycoca6`, `journalctl --user` readable
- Plasma ≥ 6.7 for true per-monitor agent desktops

## What it changes on your system

- `~/.config/kde-agent-workspace/config.json`: which desktop is the agent's, and its output.
- Only after `setup-capture`: a private copy of the Python interpreter in
  `~/.local/share/kde-agent-workspace/bin/` and
  `~/.local/share/applications/kagent-capture.desktop`, which authorise *that copy*
  for KWin's screenshot interface. `remove-capture` deletes both.
- Only with `bind-output --enable-per-output`: `kwinrc [Windows] PerOutputVirtualDesktops=true`.
- App logs go to `~/.cache/kde-agent-workspace/logs/`.

## Related

[`kde-plasma`](https://github.com/danielrosehill/Claude-KDE-Plasma-Plugin) covers
general Plasma runtime operations: panels, widgets, themes, shortcuts, KWallet. This
plugin covers only the agent workspace.

## Status

Desktop listing, creation, launch, AT-SPI driving, capture (stale and peeked) and
moving windows to an output were verified live on 2026-10-19. The Plasma ≥ 6.7
per-output binding is built from KWin source and has not yet been run. See the skill for
what to report if it fails.

## License

MIT
