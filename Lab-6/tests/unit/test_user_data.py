import base64
import re

import pytest

from stack import compute
from stack.compute import build_tier_user_data, build_user_data, launch_template_data
from stack.network import StackError

ALB = "my-alb.example.com"
DB = "my-db.example.com"


def test_app_files_are_embedded_and_round_trip(fake_settings):
    tier = fake_settings.weather
    script = build_tier_user_data(fake_settings, tier, ALB, DB)
    encoded = re.findall(r'echo "([A-Za-z0-9+/=]+)" \| base64 -d', script)
    decoded = [base64.b64decode(item).decode() for item in encoded]
    assert decoded[0] == (tier.app_dir / "app.js").read_text()
    assert decoded[1] == (tier.app_dir / "package.json").read_text()


def test_weather_gets_the_database_and_a_verifiable_certificate(fake_settings):
    script = build_tier_user_data(fake_settings, fake_settings.weather, ALB, DB)
    assert f"Environment=DB_HOST={DB}" in script
    assert "Environment=DB_PASSWORD_PARAM=/t/db-password" in script
    assert "Environment=CACHE_SECONDS=600" in script
    assert 'Environment="NWS_USER_AGENT=(itmo-444-544 weather lab, student@example.com)"' in script
    assert compute.RDS_CA_URL in script
    assert "postgresql15" in script
    assert "systemctl start weather.service" in script


def test_advisor_gets_the_alb_address_and_no_database(fake_settings):
    script = build_tier_user_data(fake_settings, fake_settings.advisor, ALB, DB)
    assert f"Environment=WEATHER_URL=http://{ALB}:8080" in script
    assert "Environment=GEMINI_MODEL=gemini-test" in script
    assert DB not in script
    assert "DB_PASSWORD_PARAM" not in script
    assert "systemctl start advisor.service" in script


def test_the_setup_commands_run_after_the_app_folder_exists(fake_settings):
    script = build_tier_user_data(fake_settings, fake_settings.weather, ALB, DB)
    assert script.index("mkdir -p /opt/app") < script.index("rds-ca.pem")


@pytest.mark.parametrize("tier_name", ["weather", "advisor"])
def test_real_user_data_is_under_16_kb(real_app_settings, tier_name):
    tier = real_app_settings.tier(tier_name)
    script = build_tier_user_data(real_app_settings, tier, ALB, DB)
    assert len(script.encode()) < 16 * 1024


def test_oversized_user_data_is_refused(fake_settings):
    tier = fake_settings.advisor
    (tier.app_dir / "app.js").write_text("x" * 20000)
    with pytest.raises(StackError, match="16384 byte limit"):
        build_user_data(fake_settings, tier, [])


def test_launch_template_user_data_is_base64_of_the_script(fake_settings):
    tier = fake_settings.advisor
    script = build_tier_user_data(fake_settings, tier, ALB, DB)
    data = launch_template_data(fake_settings, tier, script)
    assert base64.b64decode(data["UserData"]).decode() == script
    assert data["IamInstanceProfile"] == {"Name": "t-advisor-profile"}
    assert data["SecurityGroupIds"] == ["sg-placeholder"]
    assert data["TagSpecifications"][0]["Tags"] == [{"Key": "Name", "Value": "advisor-app"}]
