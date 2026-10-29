"""Settings, resolved as env vars > ~/.config/zen-harness/config.toml > defaults."""
import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

CONFIG_FILE = Path(os.environ.get("ZH_CONFIG", Path.home() / ".config/zen-harness/config.toml"))

CHOICES = {
    "if_not_running": ("launch", "instruct"),
    "if_not_listening": ("instruct", "relaunch"),
    "automation_prefs": ("skip", "apply"),
}


@dataclass(frozen=True)
class Config:
    port: int = 9222
    marionette_port: int = 0  # Marionette port when the harness starts Zen; 0 = any free port
    profile: str = ""  # profile name or path; empty = Zen's default profile
    zen_path: str = "/Applications/Zen.app/Contents/MacOS/zen"
    zen_data_dir: str = str(Path.home() / "Library/Application Support/zen")
    if_not_running: str = "launch"
    if_not_listening: str = "instruct"
    automation_prefs: str = "skip"
    headless: bool = False
    idle_timeout: int = 1800  # seconds; 0 keeps the session forever
    workspace: str = str(Path.home() / ".zen-harness")
    tab_marker: str = "\U0001F434"

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace).expanduser()

    @property
    def run_dir(self) -> Path:
        return self.workspace_path / "run"


def _coerce(name, raw):
    kind = {f.name: f.type for f in fields(Config)}[name]
    if kind in (int, "int"):
        return int(raw)
    if kind in (bool, "bool"):
        return raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "yes", "on")
    value = str(raw)
    if name in CHOICES and value not in CHOICES[name]:
        raise ValueError(f"{name} must be one of {', '.join(CHOICES[name])}, got {value!r}")
    return value


def load(env=None, config_file=None) -> Config:
    env = os.environ if env is None else env
    path = Path(config_file) if config_file else CONFIG_FILE
    values = tomllib.loads(path.read_text()) if path.is_file() else {}
    known = {f.name for f in fields(Config)}
    unknown = set(values) - known
    if unknown:
        raise ValueError(f"unknown keys in {path}: {', '.join(sorted(unknown))}")
    for name in known:
        if f"ZH_{name.upper()}" in env:
            values[name] = env[f"ZH_{name.upper()}"]
    return Config(**{k: _coerce(k, v) for k, v in values.items()})
