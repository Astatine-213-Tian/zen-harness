import pytest

from zen_harness import config, connection

PROFILES_INI = """[Profile1]
Name=Work
IsRelative=1
Path=Profiles/abc.Work

[Profile0]
Name=Default Profile
IsRelative=1
Path=Profiles/def.Default
Default=1

[Install6ED35B3CA1B5D3AF]
Default=Profiles/xyz.Default (release)
"""


def test_env_beats_file_beats_default(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('port = 9400\nif_not_listening = "relaunch"\n')
    cfg = config.load(env={"ZH_PORT": "9500"}, config_file=f)
    assert cfg.port == 9500
    assert cfg.if_not_listening == "relaunch"
    assert cfg.if_not_running == "launch"


def test_rejects_unknown_choice_and_key(tmp_path):
    with pytest.raises(ValueError, match="if_not_listening"):
        config.load(env={"ZH_IF_NOT_LISTENING": "kill"}, config_file=tmp_path / "none")
    f = tmp_path / "config.toml"
    f.write_text("prot = 1\n")
    with pytest.raises(ValueError, match="unknown keys"):
        config.load(env={}, config_file=f)


@pytest.fixture
def zen_dir(tmp_path):
    (tmp_path / "profiles.ini").write_text(PROFILES_INI)
    return tmp_path


def test_default_profile_is_the_install_default(zen_dir):
    cfg = config.Config(zen_data_dir=str(zen_dir))
    assert connection.resolve_profile(cfg) == zen_dir / "Profiles/xyz.Default (release)"


def test_profile_by_name_and_by_path(zen_dir, tmp_path):
    assert connection.resolve_profile(config.Config(zen_data_dir=str(zen_dir), profile="Work")) \
        == zen_dir / "Profiles/abc.Work"
    assert connection.resolve_profile(config.Config(profile=str(tmp_path))) == tmp_path
    with pytest.raises(connection.ConnectError, match="available: Work"):
        connection.resolve_profile(config.Config(zen_data_dir=str(zen_dir), profile="Nope"))


def test_automation_prefs_written_once_and_only_when_skipping(tmp_path):
    cfg = config.Config()
    (tmp_path / "user.js").write_text('user_pref("a", 1);')
    connection.ensure_automation_prefs(cfg, tmp_path)
    connection.ensure_automation_prefs(cfg, tmp_path)
    text = (tmp_path / "user.js").read_text()
    assert text.count(connection.PREF_LINE) == 1 and text.startswith('user_pref("a", 1);\n')
    other = tmp_path / "other"
    other.mkdir()
    connection.ensure_automation_prefs(config.Config(automation_prefs="apply"), other)
    assert not (other / "user.js").exists()


def test_instruct_mode_explains_how_to_start(tmp_path):
    cfg = config.Config(port=9399, profile=str(tmp_path), if_not_running="instruct")
    with pytest.raises(connection.ConnectError, match="--remote-debugging-port 9399"):
        connection.connect(cfg)


def test_snippets_do_not_load_the_daemon():
    # Every snippet is a new process; loading websockets and launch code costs ~30 ms each time.
    import subprocess
    import sys
    code = ("import sys, zen_harness.run; print(sorted(m for m in ('websockets', 'zen_harness.daemon', "
            "'zen_harness.connection', 'urllib.request') if m in sys.modules))")
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout.strip() == "[]"


def test_one_command_for_each_way_of_starting_zen(tmp_path):
    import shlex
    for headless in (False, True):
        cfg = config.Config(headless=headless)
        flags, flags_env = connection.zen_command(cfg, tmp_path)
        runtime, runtime_env = connection.zen_command(cfg, tmp_path, debugger_socket=tmp_path / "d.sock")
        assert "--remote-debugging-port" in flags and "--start-debugger-server" not in flags
        assert "--start-debugger-server" in runtime and "--remote-debugging-port" not in runtime
        assert connection.MARIONETTE_PREFS_ENV in flags_env and connection.MARIONETTE_PREFS_ENV not in runtime_env
        for cmd, env in ((flags, flags_env), (runtime, runtime_env)):
            assert cmd.count("--headless") == int(headless) and ("MOZ_HEADLESS" in env) == headless
        # What doctor prints is exactly what a launch runs.
        words = shlex.split(connection.shell_line(cfg, tmp_path))
        assert words == [f"{k}={v}" for k, v in flags_env.items()] + flags


def test_a_failed_launch_says_why_at_once(tmp_path):
    import os
    import subprocess
    import sys
    import time
    from conftest import PORT
    fake = tmp_path / "zen"
    fake.write_text("#!/bin/sh\necho 'Zen: something went wrong'\nexit 3\n")
    fake.chmod(0o755)
    (tmp_path / "profile").mkdir()
    env = {**os.environ, "ZH_CONFIG": str(tmp_path / "none.toml"), "ZH_WORKSPACE": str(tmp_path / "ws"),
           "ZH_PROFILE": str(tmp_path / "profile"), "ZH_PORT": str(int(PORT) + 3), "ZH_ZEN_PATH": str(fake),
           "ZH_HEADLESS": "1"}
    start = time.time()
    p = subprocess.run([sys.executable, "-m", "zen_harness.run"], input="new_tab()", env=env,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 1
    assert "Zen exited with code 3" in p.stderr and "something went wrong" in p.stderr
    assert time.time() - start < 10
