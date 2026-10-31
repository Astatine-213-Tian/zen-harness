"""Find a Zen that accepts WebDriver BiDi, or start one, and return its session URL.

The harness attaches to whatever is listening on the configured port, whichever
profile that is. `profile` only matters when Zen has to be (re)started.
"""
import configparser
import http.client
import json
import os
import shlex
import socket
import subprocess
import time
from pathlib import Path

from . import runfiles
from .config import Config

BUNDLE_ID = "app.zen-browser.zen"
PREF_LINE = 'user_pref("remote.prefs.recommended", false);'
# Prefs Firefox applies over the profile's when started with --marionette. A busy marionette.port
# makes Zen quit at startup, so launches ask for `marionette_port` (default 0: any free port).
MARIONETTE_PREFS_ENV = "MOZ_MARIONETTE_PREF_STATE_ACROSS_RESTARTS"


class ConnectError(RuntimeError):
    """Raised with a message that tells the user exactly how to fix it."""


def session_url(cfg: Config) -> str:
    return f"ws://127.0.0.1:{cfg.port}/session"


def listener(port: int):
    """'bidi', 'cdp' (a Chromium browser holds the port) or None (nothing listening)."""
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
    except OSError:
        return None
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/json/version")
        status = conn.getresponse().status
        conn.close()
    except (OSError, http.client.HTTPException):
        return "bidi"
    return "cdp" if status == 200 else "bidi"


def resolve_profile(cfg: Config) -> Path:
    """Profile directory for `cfg.profile`: a path, a profile name, or empty for Zen's default."""
    if cfg.profile and ("/" in cfg.profile or cfg.profile.startswith("~")):
        path = Path(cfg.profile).expanduser()
        if not path.is_dir():
            raise ConnectError(f"profile directory not found: {path}")
        return path
    root = Path(cfg.zen_data_dir).expanduser()
    ini = configparser.ConfigParser(interpolation=None)
    ini.optionxform = str
    if not ini.read(root / "profiles.ini"):
        raise ConnectError(f"no profiles.ini in {root}; set `profile` to a profile directory")

    def to_path(section):
        p = ini[section]["Path"]
        return root / p if ini[section].get("IsRelative", "1") == "1" else Path(p)

    profiles = [s for s in ini.sections() if s.startswith("Profile")]
    if cfg.profile:
        for s in profiles:
            if ini[s].get("Name") == cfg.profile:
                return to_path(s)
        names = ", ".join(ini[s].get("Name", "?") for s in profiles)
        raise ConnectError(f"no Zen profile named {cfg.profile!r}; available: {names}")
    # The profile Zen opens from the Dock: the install default, else the Default=1 profile.
    for s in ini.sections():
        if s.startswith("Install") and ini[s].get("Default"):
            return root / ini[s]["Default"]
    for s in profiles:
        if ini[s].get("Default") == "1":
            return to_path(s)
    raise ConnectError("could not tell which Zen profile is the default; set `profile`")


def running_zen(cfg: Config):
    """[(pid, profile_dir or None)] for each running Zen main process."""
    out = subprocess.run(["ps", "-axo", "pid=,comm="], capture_output=True, text=True).stdout
    procs = []
    for line in out.splitlines():
        pid, _, comm = line.strip().partition(" ")
        if comm.strip() == cfg.zen_path:
            procs.append((int(pid), _profile_of(int(pid))))
    return procs


def _profile_of(pid: int):
    out = subprocess.run(["lsof", "-Fn", "-p", str(pid)], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("n") and line.endswith("/.parentlock"):
            return Path(line[1:]).parent
    return None


def read_active_port(profile):
    """The port Marionette wrote to the profile's MarionetteActivePort file at startup, or None."""
    try:
        text = (Path(profile) / "MarionetteActivePort").read_text().strip()
    except OSError:
        return None
    return int(text) if text.isdigit() and 0 < int(text) < 65536 else None


def parse_lsof_ports(text):
    """Ports from `lsof -Fn` output lines such as `n127.0.0.1:2828`."""
    return {int(line.rsplit(":", 1)[1]) for line in text.splitlines()
            if line.startswith("n") and line.rsplit(":", 1)[-1].isdigit()}


def marionette_port(cfg: Config):
    """Marionette port of the Zen listening on `cfg.port`, or None if it runs without --marionette."""
    out = subprocess.run(["lsof", "-nP", f"-iTCP:{cfg.port}", "-sTCP:LISTEN", "-t"],
                         capture_output=True, text=True).stdout.split()
    if not out:
        return None
    pid = int(out[0])
    profile = _profile_of(pid)
    port = read_active_port(profile) if profile else None
    if port is None:
        return None
    # The file outlives a crash, so only trust it if that same process listens there.
    listening = subprocess.run(["lsof", "-nP", "-a", "-p", str(pid), "-iTCP", "-sTCP:LISTEN", "-Fn"],
                               capture_output=True, text=True).stdout
    return port if port in parse_lsof_ports(listening) else None


def _same(a, b) -> bool:
    return a is not None and Path(a).resolve() == Path(b).resolve()


def start_command(cfg: Config, profile: Path) -> list:
    # --marionette lets the daemon own its session through a connection whose loss ends it.
    cmd = [cfg.zen_path, "--profile", str(profile), "--remote-debugging-port", str(cfg.port), "--marionette"]
    return cmd + (["--headless"] if cfg.headless else [])


def headless_env(cfg: Config) -> dict:
    # --headless alone still shows a Dock icon for the first moment; the env var never does.
    return {"MOZ_HEADLESS": "1"} if cfg.headless else {}


def start_env(cfg: Config) -> dict:
    return {MARIONETTE_PREFS_ENV: json.dumps({"marionette.port": cfg.marionette_port}), **headless_env(cfg)}


def start_shell(cfg: Config, profile: Path) -> str:
    """start_command as a line to paste into a shell."""
    env = " ".join(f"{k}={shlex.quote(v)}" for k, v in start_env(cfg).items())
    return f"{env} {shlex.join(start_command(cfg, profile))}"


def ensure_automation_prefs(cfg: Config, profile: Path):
    """With automation_prefs=skip, stop Firefox's automation prefs from touching this profile."""
    if cfg.automation_prefs != "skip":
        return
    user_js = profile / "user.js"
    text = user_js.read_text() if user_js.exists() else ""
    if PREF_LINE not in text:
        user_js.write_text(text + ("" if text.endswith("\n") or not text else "\n")
                           + "// Added by zen-harness: keep everyday prefs when remote control is on.\n"
                           + PREF_LINE + "\n")


def launch(cfg: Config, profile: Path, timeout=30.0) -> str:
    ensure_automation_prefs(cfg, profile)
    log = runfiles.log(cfg, "zen")
    subprocess.Popen(start_command(cfg, profile), env={**os.environ, **start_env(cfg)}, stdin=subprocess.DEVNULL,
                     stdout=log.open("ab"), stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if listener(cfg.port) == "bidi":
            # Marionette starts alongside BiDi; give it a moment so the daemon can use it.
            until = min(deadline, time.time() + 5)
            while marionette_port(cfg) is None and time.time() < until:
                time.sleep(0.25)
            return session_url(cfg)
        time.sleep(0.25)
    raise ConnectError(f"started Zen but it did not open port {cfg.port} within {timeout:.0f}s; see {log}")


def quit_zen(cfg: Config, pid: int, timeout=20.0):
    """Quit gracefully so session restore brings the tabs back."""
    if len(running_zen(cfg)) == 1:
        subprocess.run(["osascript", "-e", f'tell application id "{BUNDLE_ID}" to quit'],
                       capture_output=True, timeout=timeout)
    else:
        subprocess.run(["kill", "-TERM", str(pid)])
    deadline = time.time() + timeout
    while time.time() < deadline:
        if subprocess.run(["kill", "-0", str(pid)], capture_output=True).returncode:
            return
        time.sleep(0.25)
    raise ConnectError("Zen did not quit within "
                       f"{timeout:.0f}s (a 'close tabs?' dialog may be open); quit it, then retry")


def relaunch(cfg: Config) -> str:
    profile = resolve_profile(cfg)
    for pid, prof in running_zen(cfg):
        if _same(prof, profile):
            quit_zen(cfg, pid)
    return launch(cfg, profile)


def start_runtime(cfg: Config, profile: Path, running: bool, timeout=10.0) -> str:
    """remote_mode=runtime: turn remote control on inside Zen without the automation flag.
    No restart: a running Zen is asked over a short-lived DevTools socket."""
    from . import runtime

    if cfg.port != runtime.RUNTIME_PORT:
        raise ConnectError(f"remote_mode = \"runtime\" always listens on port {runtime.RUNTIME_PORT} "
                           "(Firefox fixes it); set port = 9222 or use remote_mode = \"flags\"")
    missing = runtime.missing_prefs(profile)
    if missing:
        raise ConnectError(runtime.prefs_help(missing))
    if not running and cfg.if_not_running != "launch":
        raise ConnectError("Zen is not running. Open Zen normally, then retry.")
    sock = runtime.devtools_socket()
    try:
        if running:
            runtime.request_debugger(cfg, profile, sock)
        else:
            runfiles.private_dir(sock.parent)
            sock.unlink(missing_ok=True)
            log = runfiles.log(cfg, "zen")
            cmd = [cfg.zen_path, "--profile", str(profile), *runtime.debugger_args(sock)]
            subprocess.Popen(cmd + (["--headless"] if cfg.headless else []), stdin=subprocess.DEVNULL,
                             env={**os.environ, **headless_env(cfg)},
                             stdout=log.open("ab"), stderr=subprocess.STDOUT, start_new_session=True)
            runtime.wait_for_socket(sock, 30.0)
        runtime.start(sock)
    except (runtime.BootstrapError, OSError, subprocess.SubprocessError) as e:
        raise ConnectError(f"could not turn on remote control inside Zen: {e}") from e
    deadline = time.time() + timeout
    while time.time() < deadline:
        if listener(cfg.port) == "bidi":
            return session_url(cfg)
        time.sleep(0.2)
    raise ConnectError(f"remote control started but port {cfg.port} did not open within {timeout:.0f}s")


def connect(cfg: Config) -> str:
    kind = listener(cfg.port)
    if kind == "bidi":
        return session_url(cfg)
    if kind == "cdp":
        raise ConnectError(f"port {cfg.port} is held by a Chromium browser's DevTools, not Zen. "
                           "Free it or set ZH_PORT to another port.")
    profile = resolve_profile(cfg)
    running = any(_same(prof, profile) for _, prof in running_zen(cfg))
    if cfg.remote_mode == "runtime":
        return start_runtime(cfg, profile, running)
    if running:
        if cfg.if_not_listening == "relaunch":
            return relaunch(cfg)
        raise ConnectError(
            f"Zen is running profile '{profile.name}' without remote control, so the harness can't attach.\n"
            "Fix it one of these ways:\n"
            "  - run `zen-harness relaunch` (quits Zen and reopens it with remote control on;\n"
            "    tabs come back through session restore)\n"
            "  - set if_not_listening = \"relaunch\" in ~/.config/zen-harness/config.toml\n"
            "  - quit Zen and start it yourself with:\n"
            f"    {start_shell(cfg, profile)}")
    if cfg.if_not_running == "launch":
        return launch(cfg, profile)
    raise ConnectError("Zen is not running with remote control. Start it with:\n"
                       f"  {start_shell(cfg, profile)}")
