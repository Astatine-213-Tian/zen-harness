# Agents act only on tabs they opened or chose, one controlled tab per agent

The harness used to fall back to the tab the user was looking at whenever no tab was controlled: on a new session, after the idle timeout, or after the agent closed its own tab. The next helper call silently took the user's tab and marked it. That is the opposite of staying out of the user's way (ADR-0008, ADR-0009). So helpers now raise "no tab is controlled", and taking the user's tab is an explicit `ensure_real_tab()`.

Snippets started together now share one daemon (the port lock), so several agents, such as parallel subagents, end up sharing it too. With one controlled tab for everyone, one agent's `new_tab()` would redirect another's clicks. So the daemon keeps a controlled tab per agent id (`ZH_AGENT`), and agents without one share the `""` id's tab.

The daemon also owns the tab marker: setting an agent's tab moves the marker, a preload script limited to that tab marks every document it loads (in its own sandbox, so pages can't see or break it), and stopping removes every marker once. Before, helpers re-marked after the waits, so a page reached without a wait stayed unmarked.
