"""Shared fixtures. Unit tests use fake settings, integration tests use your real .env."""
from pathlib import Path

import pytest
from moto import mock_aws

from stack.clients import AwsClients
from stack.config import Settings
from stack.outputs import DatabaseOutputs, StackOutputs

ROOT = Path(__file__).resolve().parent.parent

FAKE_VALUES = {
    "AWS_REGION": "us-east-2", "AMI_ID": "ami-12345678", "KEY_NAME": "test-key",
    "INSTANCE_TYPE": "t3.micro", "APP_SECURITY_GROUP_ID": "sg-placeholder", "APP_PORT": "3000",
    "WEATHER_ROLE_NAME": "t-weather-role", "WEATHER_PROFILE_NAME": "t-weather-profile",
    "WEATHER_LT_NAME": "t-weather-lt", "WEATHER_TG_NAME": "t-weather-tg",
    "WEATHER_ASG_NAME": "t-weather-asg", "WEATHER_LISTENER_PORT": "8080",
    "ADVISOR_ROLE_NAME": "t-advisor-role", "ADVISOR_PROFILE_NAME": "t-advisor-profile",
    "ADVISOR_LT_NAME": "t-advisor-lt", "ADVISOR_TG_NAME": "t-advisor-tg",
    "ADVISOR_ASG_NAME": "t-advisor-asg", "ADVISOR_LISTENER_PORT": "8081",
    "ALB_NAME": "t-alb", "ALB_SG_NAME": "t-alb-sg",
    "AZ_A": "us-east-2a", "AZ_B": "us-east-2b", "RECOVERY_SLO_SECONDS": "300",
    "DB_INSTANCE_ID": "t-weather-db", "DB_INSTANCE_CLASS": "db.t4g.micro",
    "DB_ALLOCATED_STORAGE": "20", "DB_PORT": "5432", "DB_NAME": "weather",
    "DB_USER": "weatherapp", "DB_SG_NAME": "t-db-sg", "DB_SUBNET_GROUP_NAME": "t-db-subnets",
    "DB_PASSWORD_PARAM": "/t/db-password", "CACHE_SECONDS": "600",
    "GEMINI_PARAM_NAME": "/t/gemini-api-key", "GEMINI_MODEL": "gemini-test",
    "KEY_CACHE_SECONDS": "60", "CONTACT_EMAIL": "student@example.com",
}


@pytest.fixture
def fake_settings(tmp_path):
    """Settings pointing at two tiny fake app folders, so no real files are needed."""
    for name in ("weather-app", "advisor-app"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "app.js").write_text(f"console.log('{name}');\n")
        (folder / "package.json").write_text('{"name": "%s"}\n' % name)
    return Settings.from_values(FAKE_VALUES, base_dir=tmp_path)


@pytest.fixture
def real_app_settings():
    """Fake names, but the real app.js files, for checks that depend on their size."""
    return Settings.from_values(FAKE_VALUES, base_dir=ROOT)


@pytest.fixture
def env(tmp_path, monkeypatch, fake_settings):
    """A fake AWS account with the things earlier labs and Part C would already have created."""
    monkeypatch.chdir(tmp_path)  # the outputs files are written to the current folder
    with mock_aws():
        aws = AwsClients.create("us-east-2")
        vpc = aws.ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"][0]
        sg = aws.ec2.create_security_group(
            GroupName="app-sg", Description="app", VpcId=vpc["VpcId"])["GroupId"]
        aws.ec2.authorize_security_group_ingress(GroupId=sg, IpPermissions=[{
            "IpProtocol": "tcp", "FromPort": 3000, "ToPort": 3000,
            "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}])
        aws.ec2.create_key_pair(KeyName="test-key")
        ami = aws.ec2.describe_images()["Images"][0]["ImageId"]
        aws.ssm.put_parameter(Name=FAKE_VALUES["GEMINI_PARAM_NAME"], Type="SecureString",
                              Value="fake-gemini-key")
        values = dict(FAKE_VALUES, APP_SECURITY_GROUP_ID=sg, AMI_ID=ami)
        settings = Settings.from_values(values, base_dir=fake_settings.weather.app_dir.parent)
        yield settings, aws


# ---- fixtures for tests that talk to your deployed stack ----

@pytest.fixture(scope="session")
def settings():
    return Settings.from_file(ROOT / ".env")


@pytest.fixture(scope="session")
def aws(settings):
    return AwsClients.create(settings.region)


@pytest.fixture(scope="session")
def outputs():
    try:
        return StackOutputs.load(ROOT)
    except FileNotFoundError:
        pytest.skip("stack_outputs.json not found. Run python create_weather_stack.py first.")


@pytest.fixture(scope="session")
def database():
    try:
        return DatabaseOutputs.load(ROOT)
    except FileNotFoundError:
        pytest.skip("db_outputs.json not found. Run python create_database.py first.")
