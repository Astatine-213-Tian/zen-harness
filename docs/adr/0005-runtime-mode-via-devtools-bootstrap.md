---
status: accepted
---

# Opt-in runtime mode starts remote control through a short-lived DevTools socket

In flags mode, Firefox treats the browser as under automation: `navigator.webdriver` is true on every page, and some bot-protected sites react to that. No pref turns this off. Firefox's runtime start, `RemoteAgent.startAtRuntime({isBrowserAutomation: false})`, avoids both the flag and the automation prefs, but Zen 1.23 ships no button or other way to call it.

So with `remote_mode = "runtime"` the harness:
1. forwards `--start-debugger-server <0700 Unix socket>` to the running Zen, or starts Zen with that flag;
2. evaluates the runtime start for the Remote Agent and for Marionette (with its port temporarily set to 0) over Firefox's DevTools protocol (RDP);
3. closes the DevTools listeners and deletes the socket.

It is opt-in because it needs three about:config settings that let a local program open a DevTools connection with full control of the browser. The harness never sets them itself.

## Consequences

- Firefox hard-codes the runtime port to 9222 and quits the whole browser if that port is busy, so the harness refuses runtime mode on any other port.
- The user sees an "Allow remote control?" prompt, a robot icon and a red-striped address bar.
- Firefox plans to confine these sessions to a separate container (Bug 2072964). If that ships, runtime sessions lose the user's logins, and this decision needs revisiting. Switch to Zen's own Remote Control button once it ships.
