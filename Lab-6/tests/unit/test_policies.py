import json

from stack.policies import parameter_arn, read_one_secret_policy, trust_policy
from stack.runner import create_weather_stack
from tests.unit.test_stack_with_moto import with_database

ACCOUNT = "123456789012"


def _policy(aws, tier):
    return aws.iam.get_role_policy(RoleName=tier.role_name, PolicyName=tier.policy_name)["PolicyDocument"]


def test_only_ec2_may_assume_the_role():
    statement = trust_policy()["Statement"][0]
    assert statement["Principal"] == {"Service": "ec2.amazonaws.com"}
    assert statement["Action"] == "sts:AssumeRole"


def test_a_leading_slash_gives_one_slash_in_the_arn():
    expected = f"arn:aws:ssm:us-east-2:{ACCOUNT}:parameter/a/b"
    assert parameter_arn("us-east-2", ACCOUNT, "/a/b") == expected
    assert parameter_arn("us-east-2", ACCOUNT, "a/b") == expected


def test_the_policy_allows_one_action_on_one_resource():
    assert read_one_secret_policy("arn:x")["Statement"] == [
        {"Effect": "Allow", "Action": ["ssm:GetParameter"], "Resource": "arn:x"}]


def test_each_role_reads_exactly_its_own_secret_and_never_the_others(env):
    settings, aws = env
    with_database(settings, aws)
    create_weather_stack(settings, aws, iam_wait=0)
    db_arn = parameter_arn(settings.region, ACCOUNT, settings.db_password_param)
    gemini_arn = parameter_arn(settings.region, ACCOUNT, settings.gemini_param_name)

    weather = _policy(aws, settings.weather)
    advisor = _policy(aws, settings.advisor)
    assert weather == read_one_secret_policy(db_arn)
    assert advisor == read_one_secret_policy(gemini_arn)
    assert settings.gemini_param_name not in json.dumps(weather)
    assert settings.db_password_param not in json.dumps(advisor)
