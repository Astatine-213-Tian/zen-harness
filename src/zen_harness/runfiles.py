"""Where the harness keeps its run files (sockets, locks, logs), in folders only the user can open.

Snippet processes import this, so it stays standard-library only and cheap to import.
"""
import os
import stat
from pathlib import Path


class RunDirError(RuntimeError):
    pass


def private_dir(path: Path) -> Path:
    """Create `path` if needed and make sure it is the user's own, not a symlink, mode 0700."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = path.lstat()
    if stat.S_ISLNK(st.st_mode) or st.st_uid != os.getuid():
        raise RunDirError(f"{path} must be a folder owned by you, not a link; remove it and retry")
    if st.st_mode & 0o077:
        os.chmod(path, 0o700)
    return path


def socket_dir() -> Path:
    # Unix socket paths are capped at 104 bytes on macOS, so sockets stay out of the workspace.
    # Not $TMPDIR either: sandboxed agents can get different ones and would not find each other.
    return private_dir(Path(f"/tmp/zen-harness-{os.getuid()}"))


def daemon_socket(cfg) -> Path:
    return socket_dir() / f"{cfg.port}.sock"


def port_lock(cfg) -> Path:
    """Held by the one daemon serving `cfg.port` (see daemon.main)."""
    return socket_dir() / f"{cfg.port}.lock"


def devtools_socket() -> Path:
    return socket_dir() / "devtools.sock"


def run_dir(cfg) -> Path:
    return private_dir(cfg.run_dir)


def log(cfg, name) -> Path:
    return run_dir(cfg) / f"{name}.log"
