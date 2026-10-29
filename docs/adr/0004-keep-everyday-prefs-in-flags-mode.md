# In flags mode, the harness writes one line to the profile's user.js

When Zen is started with `--remote-debugging-port`, Firefox applies ~120 "recommended" automation prefs to the profile (for example it turns off Safe Browsing and crash session-restore). That's fine for a throwaway test profile but wrong for someone's everyday browser. So when the harness launches a profile with `automation_prefs = "skip"` (the default), it appends `user_pref("remote.prefs.recommended", false);` to that profile's `user.js`. This is the only change the harness ever makes to a profile. `automation_prefs = "apply"` keeps Firefox's behaviour.

## Consequences

Some of those prefs exist for automation's sake. Without `dom.file.createInChild`, `input.setFiles` fails on http(s) pages, so `upload_file` falls back to building the files inside the page.
