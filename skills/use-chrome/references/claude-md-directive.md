# Installing the CLAUDE.md directive

Read this only when asked to make agent-desktop browsing the default, or after the
agent desktop was renamed.

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
