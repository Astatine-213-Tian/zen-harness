# The daemon creates its session through Marionette, then attaches BiDi

Zen allows one WebDriver session at a time. A BiDi-only session (opened with `session.new` on `ws://…/session`) outlives its socket and can't be rejoined, so a force-killed daemon would lock Zen until it restarts.

So the daemon opens the session with Marionette's `WebDriver:NewSession` (flat capabilities, `webSocketUrl: true`) and attaches BiDi at the returned `/session/<id>` URL. Marionette deletes its session when its TCP connection closes, so even `kill -9` frees Zen. That's why launches add `--marionette`, on a free port (`marionette_port = 0`): a busy Marionette port makes Firefox quit at startup.

Without Marionette, the daemon falls back to a BiDi-only session and ends it on every catchable exit.

## Consequences

Closing *any* Marionette connection deletes whatever session is open, even another tool's. So the daemon checks BiDi `session.status` and connects to Marionette only while Zen has no session. When a session was just stopped, it waits up to 5 s for it to be released. If another tool still takes the session between that check and our `NewSession`, the daemon reports the error but keeps its Marionette connection open ("parks" it) until that tool's session ends, so it never ends someone else's session. The one deliberate exception is `zen-harness stop --force`, which connects to Marionette and closes the connection on purpose to clear a session a crashed client left behind; it warns, and agents are told to ask the user first.
