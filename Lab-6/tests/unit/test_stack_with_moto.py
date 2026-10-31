"""Run the real create and delete code against moto, an in-memory fake of AWS.

Nothing here touches your AWS account, costs money, or needs credentials.
"""
import base64
import json

import pytest

from stack import parameters
from stack.database import create_database
from stack.network import StackError
from stack.runner import create_weather_stack, delete_weather_stack


def with_database(settings, aws):
    """Most tests need the database's outputs on disk, as create_database.py leaves them."""
    outputs = create_database(settings, aws)
    outputs.save()
    return outputs


def _app_sg_rules(aws, settings):
    group = aws.ec2.describe_security_groups(GroupIds=[settings.app_sg_id])["SecurityGroups"][0]
    return [p for p in group["IpPermissions"] if p["FromPort"] == 3000]


def _user_data(aws, tier):
    version = aws.ec2.describe_launch_template_versions(
        LaunchTemplateName=tier.lt_name, Versions=["$Latest"])["LaunchTemplateVersions"][0]
    return base64.b64decode(version["LaunchTemplateData"]["UserData"]).decode()


def test_create_builds_every_resource(env):
    settings, aws = env
    with_database(settings, aws)
    outputs = create_weather_stack(settings, aws, iam_wait=0)
    for tier in settings.tiers:
        assert aws.iam.get_role_policy(RoleName=tier.role_name, PolicyName=tier.policy_name)
        profile = aws.iam.get_instance_profile(InstanceProfileName=tier.profile_name)
        assert [r["RoleName"] for r in profile["InstanceProfile"]["Roles"]] == [tier.role_name]
        assert aws.ec2.describe_launch_templates(LaunchTemplateNames=[tier.lt_name])["LaunchTemplates"]
        group = aws.autoscaling.describe_auto_scaling_groups(
            AutoScalingGroupNames=[tier.asg_name])["AutoScalingGroups"][0]
        assert (group["MinSize"], group["MaxSize"], group["DesiredCapacity"]) == (1, 1, 1)
        assert group["HealthCheckType"] == "ELB"
        tg = aws.elbv2.describe_target_groups(Names=[tier.tg_name])["TargetGroups"][0]
        assert tg["Port"] == 3000
        assert tg["HealthCheckPath"] == "/"
    listeners = aws.elbv2.describe_listeners(LoadBalancerArn=outputs.alb_arn)["Listeners"]
    forwards = {item["Port"]: item["DefaultActions"][0]["TargetGroupArn"] for item in listeners}
    assert forwards == {8080: outputs.weather_tg_arn, 8081: outputs.advisor_tg_arn}


def test_alb_comes_first_so_the_advisor_can_be_told_its_address(env):
    settings, aws = env
    with_database(settings, aws)
    outputs = create_weather_stack(settings, aws, iam_wait=0)
    assert f"WEATHER_URL=http://{outputs.alb_dns_name}:8080" in _user_data(aws, settings.advisor)


def test_weather_user_data_has_the_database_host_but_never_the_password(env):
    settings, aws = env
    database = with_database(settings, aws)
    create_weather_stack(settings, aws, iam_wait=0)
    password = parameters.read_secret(aws, settings.db_password_param)
    script = _user_data(aws, settings.weather)
    assert f"DB_HOST={database.db_host}" in script
    assert password not in script
    assert password not in _user_data(aws, settings.advisor)


def test_gemini_key_is_in_no_launch_template(env):
    settings, aws = env
    with_database(settings, aws)
    create_weather_stack(settings, aws, iam_wait=0)
    for tier in settings.tiers:
        assert "fake-gemini-key" not in _user_data(aws, tier)


def test_app_security_group_only_accepts_the_alb(env):
    settings, aws = env
    with_database(settings, aws)
    outputs = create_weather_stack(settings, aws, iam_wait=0)
    rules = _app_sg_rules(aws, settings)
    assert len(rules) == 1
    assert rules[0]["IpRanges"] == []
    assert rules[0]["UserIdGroupPairs"][0]["GroupId"] == outputs.alb_security_group_id


def test_create_twice_does_not_duplicate_anything(env):
    settings, aws = env
    with_database(settings, aws)
    first = create_weather_stack(settings, aws, iam_wait=0)
    second = create_weather_stack(settings, aws, iam_wait=0)
    assert first == second
    assert len(aws.iam.list_roles()["Roles"]) == 2
    assert len(aws.iam.list_instance_profiles()["InstanceProfiles"]) == 2
    assert len(aws.elbv2.describe_load_balancers()["LoadBalancers"]) == 1
    assert len(aws.elbv2.describe_target_groups()["TargetGroups"]) == 2
    assert len(aws.elbv2.describe_listeners(LoadBalancerArn=first.alb_arn)["Listeners"]) == 2
    assert len(aws.autoscaling.describe_auto_scaling_groups()["AutoScalingGroups"]) == 2
    assert len(aws.ec2.describe_launch_templates()["LaunchTemplates"]) == 2
    assert len(_app_sg_rules(aws, settings)) == 1
    # a second run publishes a new launch template version instead of failing
    versions = aws.ec2.describe_launch_template_versions(
        LaunchTemplateName=settings.weather.lt_name)["LaunchTemplateVersions"]
    assert len(versions) == 2


def test_create_stops_clearly_without_the_gemini_key(env):
    settings, aws = env
    with_database(settings, aws)
    aws.ssm.delete_parameter(Name=settings.gemini_param_name)
    with pytest.raises(StackError, match="store_gemini_key.py"):
        create_weather_stack(settings, aws, iam_wait=0)


def test_create_stops_clearly_without_the_database(env):
    settings, aws = env
    with pytest.raises(StackError, match="create_database.py"):
        create_weather_stack(settings, aws, iam_wait=0)


def test_create_stops_clearly_with_the_placeholder_email(env):
    settings, aws = env
    with_database(settings, aws)
    placeholder = type(settings)(**{**settings.__dict__,
                                    "contact_email": "replace-with-your-email@example.com"})
    with pytest.raises(StackError, match="CONTACT_EMAIL"):
        create_weather_stack(placeholder, aws, iam_wait=0)


def test_delete_removes_everything_and_restores_the_app_sg(env):
    settings, aws = env
    with_database(settings, aws)
    create_weather_stack(settings, aws, iam_wait=0).save()
    delete_weather_stack(settings, aws, sleep=lambda _: None)
    assert aws.elbv2.describe_load_balancers()["LoadBalancers"] == []
    assert aws.elbv2.describe_target_groups()["TargetGroups"] == []
    assert aws.autoscaling.describe_auto_scaling_groups()["AutoScalingGroups"] == []
    assert aws.ec2.describe_launch_templates()["LaunchTemplates"] == []
    assert aws.iam.list_roles()["Roles"] == []
    assert aws.iam.list_instance_profiles()["InstanceProfiles"] == []
    rules = _app_sg_rules(aws, settings)
    assert rules[0]["IpRanges"] == [{"CidrIp": "0.0.0.0/0"}]
    assert rules[0]["UserIdGroupPairs"] == []


def test_delete_leaves_the_database_and_both_secrets_alone(env):
    settings, aws = env
    with_database(settings, aws)
    create_weather_stack(settings, aws, iam_wait=0)
    delete_weather_stack(settings, aws, sleep=lambda _: None)
    assert len(aws.rds.describe_db_instances()["DBInstances"]) == 1
    assert parameters.parameter_exists(aws, settings.gemini_param_name)
    assert parameters.parameter_exists(aws, settings.db_password_param)


def test_delete_is_safe_to_run_twice(env):
    settings, aws = env
    with_database(settings, aws)
    create_weather_stack(settings, aws, iam_wait=0)
    delete_weather_stack(settings, aws, sleep=lambda _: None)
    delete_weather_stack(settings, aws, sleep=lambda _: None)  # nothing left, must not raise


def test_delete_detaches_extra_managed_policies(env):
    settings, aws = env
    with_database(settings, aws)
    create_weather_stack(settings, aws, iam_wait=0)
    extra = aws.iam.create_policy(PolicyName="extra", PolicyDocument=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "logs:PutLogEvents", "Resource": "*"}]}))
    aws.iam.attach_role_policy(RoleName=settings.weather.role_name,
                               PolicyArn=extra["Policy"]["Arn"])
    delete_weather_stack(settings, aws, sleep=lambda _: None)
    assert aws.iam.list_roles()["Roles"] == []
