"""Does the stack you deployed look the way the design says it should?

Run after create_weather_stack.py:   pytest -m integration
"""
import socket

import pytest
import requests

from stack.policies import parameter_arn
from tests.helpers import instance_ip, ssh, tier_url, wait_until

pytestmark = pytest.mark.integration


def test_every_target_becomes_healthy(aws, settings, outputs):
    def all_healthy():
        for tier in settings.tiers:
            targets = aws.elbv2.describe_target_health(
                TargetGroupArn=outputs.tg_arn(tier.name))["TargetHealthDescriptions"]
            if not targets or any(t["TargetHealth"]["State"] != "healthy" for t in targets):
                return False
        return True
    assert wait_until(all_healthy, timeout=420, interval=15), "targets never became healthy"


def _decision(aws, role_name, resource):
    role_arn = aws.iam.get_role(RoleName=role_name)["Role"]["Arn"]
    result = aws.iam.simulate_principal_policy(
        PolicySourceArn=role_arn, ActionNames=["ssm:GetParameter"], ResourceArns=[resource])
    return result["EvaluationResults"][0]["EvalDecision"]


def test_each_role_can_read_only_its_own_secret(aws, settings):
    account = aws.account_id()
    db_arn = parameter_arn(settings.region, account, settings.db_password_param)
    gemini_arn = parameter_arn(settings.region, account, settings.gemini_param_name)
    assert _decision(aws, settings.weather.role_name, db_arn) == "allowed"
    assert _decision(aws, settings.weather.role_name, gemini_arn) != "allowed"
    assert _decision(aws, settings.advisor.role_name, gemini_arn) == "allowed"
    assert _decision(aws, settings.advisor.role_name, db_arn) != "allowed"


def test_real_database_has_no_backups_and_no_public_address(aws, settings):
    db = aws.rds.describe_db_instances(
        DBInstanceIdentifier=settings.db_instance_id)["DBInstances"][0]
    assert db["BackupRetentionPeriod"] == 0
    assert db["PubliclyAccessible"] is False
    assert db["MultiAZ"] is False
    assert db["StorageEncrypted"] is True
    assert aws.rds.describe_db_snapshots(
        DBInstanceIdentifier=settings.db_instance_id)["DBSnapshots"] == []
    # With no filter: real RDS answers NotFound, not an empty list, when asked for this instance.
    backups = aws.rds.describe_db_instance_automated_backups()["DBInstanceAutomatedBackups"]
    assert settings.db_instance_id not in [b["DBInstanceIdentifier"] for b in backups]


def test_database_port_is_not_reachable_from_this_computer(settings, database):
    with pytest.raises(OSError):  # a timeout is an OSError too
        socket.create_connection((database.db_host, settings.db_port), timeout=6)


@pytest.mark.parametrize("tier_name", ["weather", "advisor"])
def test_instances_answer_only_through_the_load_balancer(aws, settings, outputs, tier_name):
    assert requests.get(tier_url(outputs, settings, tier_name) + "/", timeout=10).status_code == 200
    ip = instance_ip(aws, f"{tier_name}-app")
    with pytest.raises(requests.RequestException):
        requests.get(f"http://{ip}:{settings.app_port}/", timeout=5)


def test_tls_certificate_verifies_against_the_rds_bundle(aws, settings, database):
    """moto has no TLS. sslmode=verify-full fails unless the real certificate checks out."""
    command = (
        f"PGPASSWORD=$(aws ssm get-parameter --name {settings.db_password_param} "
        f"--with-decryption --query Parameter.Value --output text --region {settings.region}) "
        f"psql 'host={database.db_host} port={settings.db_port} dbname={settings.db_name} "
        f"user={settings.db_user} sslmode=verify-full sslrootcert=/opt/app/rds-ca.pem' "
        "-tAc 'SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()'"
    )
    result = ssh(settings, instance_ip(aws, "weather-app"), command)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "t"
