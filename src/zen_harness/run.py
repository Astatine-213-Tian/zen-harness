"""zen-harness CLI: run a Python snippet from stdin with the helpers pre-imported."""
import importlib.util
import sys
import traceback
from importlib import resources

from . import __version__, config, connection, helpers, ipc

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
  zen-harness relaunch   quit Zen and reopen it with remote control on
  zen-harness skill      print the agent skill (SKILL.md)
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


def doctor(cfg):
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
        print(resources.files("zen_harness").joinpath("SKILL.md").read_text(), end="")
        return 0
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
        else:
            print("no session")
        return 0
    if cmd == "relaunch":
        if ipc.daemon_alive(cfg):
            ipc.send(cfg, {"meta": "stop"})
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
