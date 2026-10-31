# Glossary

Domain terms for zen-harness. Use them as written in code, docs, issues and tests.

**Controlled tab**: the tab the harness acts on by default. Agents get one with `new_tab()` or `switch_tab()`; its title carries the tab marker. _Avoid_: current tab, active tab (that is the tab the user sees).

**Navigation cause**: a call from an action helper (`click`, `type_text`, `press_key`, `js`, `goto_url`, `handle_dialog`, raw `bidi`, ...) that might start a navigation in the tab it targets, or in the tab that contains its frame. Reads by the harness itself are never navigation causes.

**Grace period**: how long a navigation cause gets to show up as a navigation (300 ms) before its tab counts as settled without one.

**Settled**: a tab is settled when nothing it might be navigating to is still pending. Either the last navigation cause started a navigation that has finished (its new document is in place or, when waiting for a load, its load event fired), or the grace period passed without one. A dialog open in the tab stops it from settling until the dialog is answered. _Avoid_: loaded, idle (that is network idle).

**Page settle module**: the daemon module that tracks navigation causes, navigations, frames and dialogs per tab, and waits until a tab is settled.
