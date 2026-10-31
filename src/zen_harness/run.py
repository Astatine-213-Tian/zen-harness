"""zen-harness CLI: run a Python snippet from stdin with the helpers pre-imported."""
import importlib.util
import sys
import traceback

# Only what every snippet needs: the daemon, websockets and launch code load on demand.
from . import __version__, config, helpers, ipc

HELP = f"""zen-harness {__version__}: let an agent drive your real Zen browser.

Run a snippet (helpers are pre-imported; the daemon starts on demand):
  zen-harness <<'PY'
  new_tab("https://example.com")
  wait_for_load()
  print(page_info())
  PY

Commands:
  zen-harness doctor     show config, Zen processes, port and session state
  zen-harness status     is the session open, and which tab is controlled
  zen-harness stop       end the session (frees Zen for other tools)
  zen-harness stop --force  also end a session left open by a crashed client or another
                         tool (needs Zen's Marionette; ask the user first)
  zen-harness relaunch   quit Zen and reopen it with remote control on
  zen-harness skill      print the agent skill (SKILL.md)
  zen-harness notes      list interaction notes (iframes, uploads, ...); notes <topic> prints one
  zen-harness --version

Config: env ZH_* > {config.CONFIG_FILE} > defaults. See README.md.
"""


def _namespace():
    ns = {k: v for k, v in vars(helpers).items() if not k.startswith("_")}
    extra = helpers.CFG.workspace_path / "agent_helpers.py"
    if extra.is_file():
        spec = importlib.util.spec_from_file_location("zen_harness_agent_helpers", extra)
        mod = importlib.util.module_from_spec(spec)
        mod.__dict__.update(ns)
        spec.loader.exec_module(mod)
        ns.update({k: v for k, v in vars(mod).items() if not k.startswith("_")})
    return ns


def run_snippet(code):
    cfg = helpers.CFG
    try:
        ipc.ensure_daemon(cfg)
    except RuntimeError as e:
        print(f"zen-harness: {e}", file=sys.stderr)
        return 1
    try:
        exec(compile(code, "<snippet>", "exec"), _namespace())
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    except Exception:
        traceback.print_exc()
        return 1
    return 0


SESSION_MODES = {
    "marionette": "session via Marionette (ends even if the daemon is force-killed)",
    "bidi": "session is BiDi-only (a force-killed daemon locks Zen until it restarts; "
            "`zen-harness relaunch` adds --marionette)",
}


def notes(topic=None):
    """List the interaction notes with their one-line summaries, or print one."""
    from importlib import resources
    folder = resources.files("zen_harness").joinpath("interaction-skills")
    found = {p.name[:-3]: p for p in folder.iterdir() if p.name.endswith(".md")}
    if topic is None:
        width = max(map(len, found))
        print("Interaction notes: read one when stuck on a browser mechanic.\n")
        for name in sorted(found):
            # A note is "# Title", a blank line, then its one-line summary.
            summary = next((line for line in found[name].read_text().splitlines()[1:] if line.strip()), "")
            print(f"  {name:<{width}}  {summary}")
        print("\nzen-harness notes <topic>")
        return 0
    name = topic.removesuffix(".md")
    if name not in found:
        print(f"zen-harness: no note {topic!r}; topics: {', '.join(sorted(found))}", file=sys.stderr)
        return 2
    print(found[name].read_text(), end="")
    return 0


def doctor(cfg):
    from . import connection
    print(f"zen-harness {__version__}")
    print(f"config file: {config.CONFIG_FILE} ({'found' if config.CONFIG_FILE.is_file() else 'not found, using defaults'})")
    for k, v in vars(cfg).items():
        print(f"  {k} = {v!r}")
    try:
        profile = connection.resolve_profile(cfg)
        print(f"profile used when starting Zen: {profile}")
    except connection.ConnectError as e:
        profile = None
        print(f"profile: ERROR {e}")
    procs = connection.running_zen(cfg)
    print(f"Zen processes: {len(procs)}")
    for pid, prof in procs:
        print(f"  pid {pid}: {prof}")
    kind = connection.listener(cfg.port)
    print(f"port {cfg.port}: {({'bidi': 'Zen/Firefox remote control (BiDi)', 'cdp': 'held by a Chromium browser'}).get(kind, 'nothing listening')}")
    if kind == "bidi":
        mport = connection.marionette_port(cfg)
        print(f"marionette: {f'port {mport}' if mport else 'off (Zen was started without --marionette)'}")
    alive = ipc.daemon_alive(cfg)
    if alive:
        mode = ipc.send(cfg, {"meta": "ping"}).get("mode")
        print(f"session daemon: running; {SESSION_MODES.get(mode, 'session kind unknown')}")
        print(f"controlled tab: {ipc.send(cfg, {'meta': 'current'})['context'] or '(none yet)'}")
    else:
        print("session daemon: not running"
              + (f"; next {SESSION_MODES['marionette' if mport else 'bidi']}" if kind == "bidi" else ""))
    if profile and cfg.remote_mode == "runtime":
        from . import runtime
        missing = runtime.missing_prefs(profile)
        print("runtime mode: " + ("ready; the next call turns remote control on inside Zen, no restart"
                                  if not missing else runtime.prefs_help(missing)))
    elif profile and not kind:
        print(f"start command: {connection.start_shell(cfg, profile)}")
    return 0


def main():
    args = sys.argv[1:]
    cfg = helpers.CFG
    if not args:
        if sys.stdin.isatty():
            print(HELP, end="")
            return 2
        return run_snippet(sys.stdin.read())
    cmd = args[0]
    if cmd in ("-h", "--help", "help"):
        print(HELP, end="")
        return 0
    if cmd == "--version":
        print(__version__)
        return 0
    if cmd in ("doctor", "--doctor"):
        return doctor(cfg)
    if cmd == "skill":
        from importlib import resources
        print(resources.files("zen_harness").joinpath("SKILL.md").read_text(), end="")
        return 0
    if cmd == "notes":
        return notes(args[1] if len(args) > 1 else None)
    if cmd == "status":
        if not ipc.daemon_alive(cfg):
            print("no session")
            return 1
        print(f"session open on port {cfg.port}; controlled tab: "
              f"{ipc.send(cfg, {'meta': 'current'})['context'] or '(none yet)'}")
        return 0
    if cmd == "stop":
        if ipc.daemon_alive(cfg):
            ipc.send(cfg, {"meta": "stop"})
            print("session ended")
        elif "--force" not in args:
            print("no session")
        if "--force" not in args:
            return 0
        print("zen-harness: --force ends whatever remote-control session Zen has open, "
              "even another tool's.", file=sys.stderr)
        from . import daemon
        try:
            print(daemon.force_end_session(cfg))
        except daemon.BiDiError as e:
            print(f"zen-harness: {e}", file=sys.stderr)
            return 1
        return 0
    if cmd == "relaunch":
        if ipc.daemon_alive(cfg):
            ipc.send(cfg, {"meta": "stop"})
        from . import connection
        try:
            print(f"Zen is listening at {connection.relaunch(cfg)}")
        except connection.ConnectError as e:
            print(f"zen-harness: {e}", file=sys.stderr)
            return 1
        return 0
    print(f"zen-harness: unknown command {cmd!r}\n\n{HELP}", file=sys.stderr, end="")
    return 2


if __name__ == "__main__":
    sys.exit(main())
