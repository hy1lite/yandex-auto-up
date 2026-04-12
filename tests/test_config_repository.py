import json
from pathlib import Path

from yauto.config.repository import ConfigRepository
from yauto.models import VMProfile
from yauto.paths import AppPaths


def make_paths(base: Path) -> AppPaths:
    return AppPaths(
        config_dir=base / "config",
        profile_dir=base / "config" / "profiles",
        state_dir=base / "state",
        runtime_dir=base / "run",
        config_file=base / "config" / "config.json",
        keys_dir=base / "config" / "keys",
        keys_notice_file=base / "config" / "keys" / "ПРОЧИТАЙ МЕНЯ.txt",
        legacy_service_account_file=base / "config" / "service-account.json",
        state_file=base / "state" / "state.json",
        events_file=base / "state" / "events.jsonl",
        pid_file=base / "run" / "daemon.pid",
    )


SA_PAYLOAD = {"id": "key-a", "service_account_id": "sa-a", "private_key": "pem-a"}


def test_profile_roundtrip(tmp_path: Path):
    repo = ConfigRepository(make_paths(tmp_path))
    profile = VMProfile(name="vm-a", folder_id="folder-a", instance_id="inst-a", check_host="10.0.0.1")
    repo.save_profile(profile)

    loaded = repo.get_profile(profile.profile_id)
    assert loaded is not None
    assert loaded.name == "vm-a"
    assert loaded.instance_id == "inst-a"


def test_key_files_detected_by_content_not_extension(tmp_path: Path):
    """Keys with any extension (or none) are found if content is valid."""
    repo = ConfigRepository(make_paths(tmp_path))
    keys_dir = repo.get_keys_dir()

    payload_a = {"id": "key-a", "service_account_id": "sa-a", "private_key": "pem-a"}
    payload_b = {"id": "key-b", "service_account_id": "sa-b", "private_key": "pem-b"}
    (keys_dir / "a.json").write_text(json.dumps(payload_a), encoding="utf-8")
    (keys_dir / "b.txt").write_text(json.dumps(payload_b), encoding="utf-8")
    (keys_dir / "not-a-key.json").write_text('{"hello": "world"}', encoding="utf-8")
    (keys_dir / "garbage.bin").write_bytes(b"\x00\x01\x02")

    files = repo.validate_keys()
    names = [p.name for p in files]
    assert "a.json" in names
    assert "b.txt" in names
    assert "not-a-key.json" not in names
    assert "garbage.bin" not in names


def test_save_service_account_stores_key_in_keys_dir(tmp_path: Path):
    repo = ConfigRepository(make_paths(tmp_path))

    repo.save_service_account(json.dumps({"id": "key-main", "service_account_id": "sa-main", "private_key": "pem-main"}))

    assert (repo.get_keys_dir() / "sa-main-key-main.json").exists()


def test_legacy_single_file_is_rescued(tmp_path: Path):
    """Legacy service-account.json in config root is moved to keys/."""
    paths = make_paths(tmp_path)
    paths.config_dir.mkdir(parents=True)
    paths.legacy_service_account_file.write_text(json.dumps(SA_PAYLOAD), encoding="utf-8")

    repo = ConfigRepository(paths)

    assert not paths.legacy_service_account_file.exists()
    assert (repo.get_keys_dir() / "service-account.json").exists()


def test_stray_key_in_config_root_is_rescued(tmp_path: Path):
    """A SA key file dropped in config root (not keys/) is auto-rescued."""
    paths = make_paths(tmp_path)
    paths.config_dir.mkdir(parents=True)
    stray = paths.config_dir / "my-key.json"
    stray.write_text(json.dumps(SA_PAYLOAD), encoding="utf-8")

    repo = ConfigRepository(paths)

    assert not stray.exists()
    assert (repo.get_keys_dir() / "my-key.json").exists()
    assert len(repo.list_key_files()) == 1


def test_legacy_directory_is_rescued(tmp_path: Path):
    """Keys from old service-accounts/ dir are moved to keys/."""
    paths = make_paths(tmp_path)
    paths.config_dir.mkdir(parents=True)
    legacy_dir = paths.config_dir / "service-accounts"
    legacy_dir.mkdir()
    (legacy_dir / "old-key.json").write_text(json.dumps(SA_PAYLOAD), encoding="utf-8")

    repo = ConfigRepository(paths)

    assert not legacy_dir.exists()
    assert (repo.get_keys_dir() / "old-key.json").exists()


def test_diagnose_keys_dir_reports_invalid_files(tmp_path: Path):
    repo = ConfigRepository(make_paths(tmp_path))
    keys_dir = repo.get_keys_dir()
    (keys_dir / "good.json").write_text(json.dumps(SA_PAYLOAD), encoding="utf-8")
    (keys_dir / "bad.json").write_text('{"not": "a key"}', encoding="utf-8")

    diag = repo.diagnose_keys_dir()

    assert len(diag["valid"]) == 1
    assert len(diag["invalid"]) == 1
    assert diag["invalid"][0][0].name == "bad.json"


def test_notice_file_not_counted_as_key(tmp_path: Path):
    """The ПРОЧИТАЙ МЕНЯ.txt notice file should not be treated as an invalid key."""
    repo = ConfigRepository(make_paths(tmp_path))
    assert repo.get_keys_notice_file().exists()

    diag = repo.diagnose_keys_dir()
    assert len(diag["valid"]) == 0
    assert len(diag["invalid"]) == 0
