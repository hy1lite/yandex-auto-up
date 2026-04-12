from yauto.models import AppConfig, VMProfile


def test_app_config_defaults():
    config = AppConfig()
    assert config.service_name == "yandex-auto-up"
    assert config.language == "en"
    assert config.telegram.enabled is False


def test_profile_has_generated_id():
    profile = VMProfile(name="demo", folder_id="folder", instance_id="instance", check_host="1.1.1.1")
    assert len(profile.profile_id) == 8
    assert profile.enabled is True
