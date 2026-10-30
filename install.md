# Set up zen-harness (instructions for an AI agent)

You are an AI coding agent (Claude Code, Codex, or similar). The user asked you to set up **zen-harness**, which lets you control their real [Zen browser](https://zen-browser.app) (tabs, logins, profile) by piping Python snippets into the `zen-harness` command. Follow these steps in order. Run the commands yourself; ask the user only where a step says so.

## 1. Check the machine

```bash
uname -s                                              # must be Darwin (macOS only for now)
test -x /Applications/Zen.app/Contents/MacOS/zen && echo "Zen found"
command -v uv && uv --version
```

- Not macOS: stop and tell the user zen-harness is macOS-only for now.
- Zen missing: ask the user to install it from https://zen-browser.app, then continue. If Zen lives elsewhere, note its binary path for step 4 (`zen_path`).
- `uv` missing: ask the user before installing it. With their OK: `brew install uv` (or the official installer at https://docs.astral.sh/uv/).

## 2. Install the CLI

```bash
uv tool install git+https://github.com/Astatine-213-Tian/zen-harness
zen-harness --version
```

If `zen-harness` is not found afterwards, run `uv tool update-shell` and tell the user to open a new terminal (or call it via `~/.local/bin/zen-harness`).

## 3. Install the skill, so future sessions know how to use it

The skill text is `zen-harness skill`. Put it where your agent loads skills:

- **Claude Code:**
  ```bash
  mkdir -p ~/.claude/skills/zen-harness && zen-harness skill > ~/.claude/skills/zen-harness/SKILL.md
  ```
- **Other agents:** save the output of `zen-harness skill` wherever your agent reads skills or standing instructions (for example a skills folder, or append it to `AGENTS.md`).

## 4. Ask the user two preferences

zen-harness never decides these on its own. Ask the user:

1. **Which Zen profile should agents use?** Default: their main (default) profile, which has their logins. `zen-harness doctor` prints the profile it would use.
2. **If Zen is open without remote control, may agents restart Zen automatically?** Restarting is graceful and Zen reopens their tabs. Answers: "yes, restart automatically" or "no, tell me what to do".

Record the answers in the agent's global instructions (Claude Code: `~/.claude/CLAUDE.md`; others: their equivalent). Adapt this block:

```markdown
## Browser tasks that need my logins

- Use **zen-harness** (via its skill) against my Zen browser, main profile.
- If Zen is running without remote control, restart it automatically with
  `zen-harness relaunch` without asking me first.  <!-- or: "tell me and wait" -->
- Work in background tabs you open, leave my own tabs alone, and run
  `zen-harness stop` when the task is done.
```

### Optional: hide automation from websites (runtime mode)

By default Zen is started with automation flags, so websites can see `navigator.webdriver = true` and some bot-protected sites react to it. Runtime mode turns remote control on inside the already-running Zen instead: no restart, and websites see a normal browser. Offer it to the user, explaining the trade-off. Only set it up if they say yes.

- **Cost:** three about:config settings stay on. They let a local program open a DevTools connection with full control of the browser. zen-harness opens one only for a moment, on a private socket, and closes it again.
- **What the user sees:** a robot icon and a red-striped address bar while remote control is on, plus an "Allow remote control?" prompt (and possibly a DevTools "Allow connection?" prompt) the first time per browser session.
- **Port:** port 9222 must stay free for Zen. Chrome's remote debugging must use another port.

If they agree, ask the user to open `about:config` in Zen themselves and set each of these to `true` (do not edit their prefs files yourself):

```text
remote.experimental.dynamicstart.enabled
devtools.chrome.enabled
devtools.debugger.remote-enabled
```

Then add `remote_mode = "runtime"` to `~/.config/zen-harness/config.toml`, and run `zen-harness doctor`. It should say `runtime mode: ready`.

### Config file

Only if the user wants a non-default profile or port, or runtime mode, also write `~/.config/zen-harness/config.toml`:

```toml
profile = "Work"              # profile name from Zen, or a profile folder path
# remote_mode = "runtime"         # hide automation from websites (see above)
# foreground = "allow"            # let agents show a tab/window when a page stalls (default: never)
# port = 9222
# if_not_listening = "relaunch"   # make the harness itself restart Zen automatically
```

## 5. Check the setup

```bash
zen-harness doctor
```

Read the output:

- `port 9222: Zen/Firefox remote control (BiDi)`: ready, go to step 6.
- `nothing listening` and a Zen process is listed: Zen is open without remote control. If the user allowed automatic restarts, run `zen-harness relaunch`; otherwise ask first (it quits and reopens Zen).
- `nothing listening` and no Zen process: fine; the first snippet starts Zen with remote control on.
- `held by a Chromium browser`: Chrome is using port 9222 for its own remote debugging. Ask the user to turn that off, or set `port = 9223` in the config file.

## 6. Smoke test (read-only)

```bash
zen-harness <<'PY'
new_tab("https://example.com")
wait_for_load()
print(page_info()["title"])
print(snapshot())
close_tab()
PY
zen-harness stop
```

Expected: `🐴 Example Domain` and one line like `@e1 link "Learn more"`. Tell the user setup is done and give one example of what they can now ask, e.g. "Search Expedia for flights from Toronto to Tokyo next month."

## If something fails

| Message | What to do |
|---|---|
| `Zen is running profile '…' without remote control` | Step 5, second bullet. |
| `Zen already has a remote-control session open` | Another tool holds Zen's single automation session, or a crashed client left it open. Ask the user to stop the other tool; if nothing else should be using Zen, and with the user's OK, run `zen-harness stop --force` (or `zen-harness relaunch`). |
| `Zen did not quit within 20s` | A "close tabs?" dialog is probably open in Zen. Ask the user to answer it, then retry. |
| `no Zen profile named …` | The message lists the available names; fix `profile` in the config. |
| Anything else | Run `zen-harness doctor` and show its output to the user. |

## Update or remove

```bash
uv tool upgrade zen-harness                    # update; then re-run step 3 to refresh the skill
uv tool uninstall zen-harness && rm -rf ~/.claude/skills/zen-harness
```

`~/.zen-harness` holds saved workflows (`domain-skills/`, `agent_helpers.py`); delete it only if the user says so.
