# Agents drive Zen with Python snippets over WebDriver BiDi, not an MCP server

Zen is Firefox-based and has no Chrome DevTools Protocol, so CDP tools (browser-harness, agent-browser, Chrome DevTools MCP) can't attach to it. WebDriver BiDi is the protocol Firefox keeps. We copy browser-harness's working style and helper names, but share no code with it: the agent pipes a short Python snippet into `zen-harness`, helpers are pre-imported, and a background daemon holds the browser session. That keeps token use low, because there are no tool schemas in every turn and the agent prints only what it needs.

Snippets run in the CLI process, not inside the daemon, so a crashing or looping snippet can't take the session down. The cost is ~50–100 ms of Python startup per call.

## Considered options

- **Mozilla's `firefox-devtools-mcp`:** works with Firefox and can attach to a running one, but it's an MCP server, so its tool definitions sit in context every turn and page snapshots come back inline.
- **Playwright's Firefox:** drives its own bundled Firefox build, not the user's Zen with its logins.
