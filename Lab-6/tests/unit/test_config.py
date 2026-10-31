import pytest

from stack.config import ConfigError, Settings, load_dotenv
from tests.conftest import FAKE_VALUES


def test_values_become_settings():
    settings = Settings.from_values(FAKE_VALUES)
    assert settings.db_instance_class == "db.t4g.micro"
    assert settings.db_allocated_storage == 20
    assert settings.cache_seconds == 600
    assert settings.weather.listener_port == 8080
    assert settings.advisor.listener_port == 8081


def test_each_tier_is_given_its_own_secret():
    settings = Settings.from_values(FAKE_VALUES)
    assert settings.weather.secret_param == FAKE_VALUES["DB_PASSWORD_PARAM"]
    assert settings.advisor.secret_param == FAKE_VALUES["GEMINI_PARAM_NAME"]


def test_missing_keys_are_named():
    values = {k: v for k, v in FAKE_VALUES.items() if k not in ("DB_NAME", "GEMINI_MODEL")}
    with pytest.raises(ConfigError, match="DB_NAME, GEMINI_MODEL"):
        Settings.from_values(values)


def test_non_numeric_setting_gives_a_clear_error():
    with pytest.raises(ConfigError, match="CACHE_SECONDS must be a whole number, got 'soon'"):
        Settings.from_values(dict(FAKE_VALUES, CACHE_SECONDS="soon"))


def test_ssh_key_defaults_to_the_key_name_and_can_be_overridden(tmp_path):
    assert Settings.from_values(FAKE_VALUES, tmp_path).ssh_key_path == str(tmp_path / "test-key.pem")
    custom = Settings.from_values(dict(FAKE_VALUES, SSH_KEY_PATH="/home/k.pem"), tmp_path)
    assert custom.ssh_key_path == "/home/k.pem"


def test_dotenv_skips_comments_and_strips_quotes(tmp_path):
    path = tmp_path / ".env"
    path.write_text('# comment\n\nA=1\nB="two"\n')
    assert load_dotenv(path) == {"A": "1", "B": "two"}
