# Navigations the harness starts never open a "leave page?" prompt

Zen always selects a tab to show its beforeunload prompt, and focuses its window if Zen is the active app ("We always switch tabs for beforeunload tab-modal prompts" in Firefox's Tabbrowser). An agent navigating its background tab away from a page with unsaved changes would pull the user's view to that tab, breaking the promise that agents stay out of the user's way (ADR-0008). Notion, for one, arms beforeunload whenever a save is pending.

The prompt can't be kept in a background tab from outside: stopping Tabbrowser's handler needs chrome-privileged code, which Marionette only runs when Zen starts with `-remote-allow-system-access`, a flag that gives any remote client full system access. There is also no pref for it.

So `goto_url` and `click()` on a link ask the page first, by dispatching a synthetic `BeforeUnloadEvent` (no prompt). If the page says it would block, they wait up to `save_wait` seconds for it to stop, since apps clear the handler once their save lands. Then they raise `UnsavedChanges`, and the agent decides: wait more, or `leave=True` to discard. Before navigating, they add a capture-phase `beforeunload` listener for a few seconds that stops the page's own handlers, so the real prompt never opens.

Navigations the page starts itself can still prompt; `wait_for_load()` and `wait_for_element()` raise `DialogOpen` at once, so the agent notices instead of waiting on the old page. `close_tab()` already skips beforeunload (BiDi's `browsingContext.close` default).
