"""Run the real database code against moto. No AWS account, no cost, no credentials."""
import logging

import pytest
from botocore.exceptions import ClientError

from stack import database, parameters
from stack.database import create_database, create_instance_request, delete_database


def _instance(aws, settings):
    return aws.rds.describe_db_instances(
        DBInstanceIdentifier=settings.db_instance_id)["DBInstances"][0]


def _db_rules(aws, group_id):
    group = aws.ec2.describe_security_groups(GroupIds=[group_id])["SecurityGroups"][0]
    return group["IpPermissions"]


def test_database_has_the_free_tier_private_no_backup_settings(env):
    settings, aws = env
    create_database(settings, aws)
    db = _instance(aws, settings)
    assert db["DBInstanceClass"] == "db.t4g.micro"
    assert db["AllocatedStorage"] == 20
    assert db["BackupRetentionPeriod"] == 0
    assert db["MultiAZ"] is False
    assert db["PubliclyAccessible"] is False
    assert db["StorageEncrypted"] is True
    assert db["DeletionProtection"] is False


def test_request_has_the_settings_moto_does_not_report():
    """moto does not store every field, so check what we ask AWS for as well."""
    from stack.config import Settings
    from tests.conftest import FAKE_VALUES
    request = create_instance_request(Settings.from_values(FAKE_VALUES), "sg-1", "pw")
    assert request["Engine"] == "postgres"
    assert request["StorageType"] == "gp2"
    assert request["AvailabilityZone"] == "us-east-2a"
    assert request["VpcSecurityGroupIds"] == ["sg-1"]


def test_delete_request_leaves_nothing_behind():
    from stack.config import Settings
    from tests.conftest import FAKE_VALUES
    request = database.delete_instance_request(Settings.from_values(FAKE_VALUES))
    assert request["SkipFinalSnapshot"] is True
    assert request["DeleteAutomatedBackups"] is True


def test_database_port_is_open_to_the_app_group_and_no_cidr(env):
    settings, aws = env
    outputs = create_database(settings, aws)
    rules = _db_rules(aws, outputs.db_security_group_id)
    assert len(rules) == 1
    assert (rules[0]["FromPort"], rules[0]["ToPort"]) == (5432, 5432)
    assert rules[0]["IpRanges"] == []
    assert [p["GroupId"] for p in rules[0]["UserIdGroupPairs"]] == [settings.app_sg_id]


def test_password_is_random_stored_encrypted_and_never_logged(env, caplog):
    settings, aws = env
    with caplog.at_level(logging.DEBUG, logger="stack"):
        create_database(settings, aws)
    stored = aws.ssm.get_parameter(Name=settings.db_password_param)["Parameter"]
    password = parameters.read_secret(aws, settings.db_password_param)
    assert stored["Type"] == "SecureString"
    assert len(password) == 32
    assert password not in caplog.text


def test_outputs_files_hold_the_address_but_no_password(env, tmp_path):
    settings, aws = env
    outputs = create_database(settings, aws)
    outputs.save()
    password = parameters.read_secret(aws, settings.db_password_param)
    for name in ("db_outputs.json", "db_outputs.env"):
        text = (tmp_path / name).read_text()
        assert outputs.db_host in text
        assert password not in text


def test_create_twice_changes_nothing(env):
    settings, aws = env
    first = create_database(settings, aws)
    password = parameters.read_secret(aws, settings.db_password_param)
    second = create_database(settings, aws)
    assert first == second
    assert parameters.read_secret(aws, settings.db_password_param) == password
    assert len(aws.rds.describe_db_instances()["DBInstances"]) == 1
    assert len(aws.rds.describe_db_subnet_groups()["DBSubnetGroups"]) == 1
    assert len(_db_rules(aws, first.db_security_group_id)) == 1


def test_create_puts_back_a_rule_that_was_removed(env):
    settings, aws = env
    outputs = create_database(settings, aws)
    from stack import network
    network.block_app_from_database(aws, settings, outputs.db_security_group_id)
    assert _db_rules(aws, outputs.db_security_group_id) == []
    create_database(settings, aws)
    assert len(_db_rules(aws, outputs.db_security_group_id)) == 1


def test_delete_leaves_no_database_snapshot_or_password(env, tmp_path):
    settings, aws = env
    create_database(settings, aws).save()
    delete_database(settings, aws, sleep=lambda _: None)
    assert aws.rds.describe_db_instances()["DBInstances"] == []
    assert aws.rds.describe_db_snapshots()["DBSnapshots"] == []
    assert aws.rds.describe_db_subnet_groups()["DBSubnetGroups"] == []
    with pytest.raises(ClientError, match="ParameterNotFound"):
        aws.ssm.get_parameter(Name=settings.db_password_param)
    groups = [g["GroupName"] for g in aws.ec2.describe_security_groups()["SecurityGroups"]]
    assert settings.db_sg_name not in groups
    assert not (tmp_path / "db_outputs.json").exists()


def test_delete_keeps_the_gemini_key(env):
    settings, aws = env
    create_database(settings, aws)
    delete_database(settings, aws, sleep=lambda _: None)
    assert parameters.parameter_exists(aws, settings.gemini_param_name)


def test_delete_is_safe_to_run_twice(env):
    settings, aws = env
    create_database(settings, aws)
    delete_database(settings, aws, sleep=lambda _: None)
    delete_database(settings, aws, sleep=lambda _: None)


def test_delete_works_when_nothing_was_ever_created(env):
    settings, aws = env
    delete_database(settings, aws, sleep=lambda _: None)
