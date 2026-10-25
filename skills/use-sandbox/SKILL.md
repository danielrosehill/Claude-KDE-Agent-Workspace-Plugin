---
name: use-sandbox
description: Test or debug GUI and terminal apps in a headless sandbox KWin (private D-Bus, never on the user's screen or focus). Use on "use the sandbox", "test it in the sandbox", "don't disturb my desktop".
---

# Use the sandbox

A sandbox is a second, headless KWin (`kwin_wayland --virtual`) with its own D-Bus session
bus and its own `XDG_RUNTIME_DIR`. Apps started in it never draw on the user's monitors,
never take keyboard focus and don't register on the user's session bus. It is stricter
than the agent desktop (`test-app-in-agent-workspace`): on the agent desktop a new window
still takes focus for a moment before `launch` hands it back, and the user notices.

Use the sandbox by default when testing anything that opens windows or terminals, unless
the user needs to see or use the result.

```bash
KAGENT="${CLAUDE_PLUGIN_ROOT}/scripts/kagent.py"
"$KAGENT" sandbox start                 # idempotent; --width/--height (default 1920x1080), --name
"$KAGENT" --sandbox launch --any-new-window -- konsole --separate
"$KAGENT" --sandbox windows             # every window in the sandbox
"$KAGENT" --sandbox capture --screen Virtual-0 -o shot.png    # always current, no --peek
"$KAGENT" --sandbox a11y-tree <pid>     # AT-SPI on the sandbox's own a11y bus
"$KAGENT" sandbox run -- qdbus6         # any command with the sandbox env, foreground
"$KAGENT" sandbox stop                  # ends every process started in it
```

`--sandbox` goes **before** the subcommand. `--sandbox-name NAME` picks another sandbox.
Read screenshots with the Read tool; they're the only way to see the sandbox.

## Running something that launches its own windows

A tool that starts Konsole or another app itself (not via `launch`) is run through
`sandbox run`, so its children inherit the sandbox env:

```bash
"$KAGENT" sandbox run -- python3 path/to/tool.py ...
"$KAGENT" sandbox run -- bash -c 'for s in $(qdbus6 | grep konsole); do echo $s; done'
```

Probe D-Bus services the same way. `qdbus6` outside `sandbox run` talks to the user's bus.

## Rules

- **Stop it when done** (`sandbox stop`). It holds a KWin, a dbus-daemon and whatever ran inside.
- Commands that act on the real desktop refuse `--sandbox`: `create`, `rename`, `remove`,
  `show`, `switch`, `bind-output`, `browser-window`, `claude-md`, `setup-capture`.
- There's no Xwayland: X11-only apps fail to start rather than appear on the real screen.
- `capture` needs the one-time `setup-capture` helper (run without `--sandbox`).
- Programs in the sandbox still share the user's home directory, files and network.
  The sandbox isolates the display, input, focus and session bus. It does not isolate
  side effects. A real `claude --resume`, `git push` or email send run inside it still
  happens. Swap in a harmless command (`echo`, `--version`) to test mechanics.

Why a private runtime dir: see `reference/findings.md` → "Sandbox".
