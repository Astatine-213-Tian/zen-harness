import plistlib

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


def test_bundle_id_comes_from_the_app_holding_zen_path(tmp_path):
    app = tmp_path / "Firefox.app"
    (app / "Contents/MacOS").mkdir(parents=True)
    with open(app / "Contents/Info.plist", "wb") as f:
        plistlib.dump({"CFBundleIdentifier": "org.mozilla.firefox"}, f)
    assert connection.bundle_id(config.Config(zen_path=str(app / "Contents/MacOS/firefox"))) \
        == "org.mozilla.firefox"
    # Outside an .app (or without a readable Info.plist) relaunch falls back to SIGTERM.
    assert connection.bundle_id(config.Config(zen_path=str(tmp_path / "bin/firefox"))) is None
    assert connection.bundle_id(config.Config(zen_path=str(tmp_path / "Other.app/Contents/MacOS/x"))) is None
