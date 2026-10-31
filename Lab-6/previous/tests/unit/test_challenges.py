"""Part J challenges that run without AWS (1 and 2)."""
import pytest
from moto import mock_aws

from stack import compute
from stack.clients import AwsClients
from stack.config import ConfigError, Settings
from tests.conftest import FAKE_VALUES


def test_non_numeric_slo_gives_a_clear_config_error():
    """Challenge 2: 'fast' is not a number of seconds, and the message should say which key."""
    values = dict(FAKE_VALUES, RECOVERY_SLO_SECONDS="fast")
    with pytest.raises(ConfigError) as err:
        Settings.from_values(values)
    assert "RECOVERY_SLO_SECONDS" in str(err.value) and "'fast'" in str(err.value)


@pytest.mark.parametrize("tier_name", ["uploader", "viewer"])
def test_launch_template_tags_instances_with_the_tier_name(fake_settings, tier_name):
    """Challenge 1 (unit half): the stored template tags every instance Name=<tier>-app."""
    tier = fake_settings.tier(tier_name)
    with mock_aws():
        aws = AwsClients.create("us-east-2")
        compute.ensure_launch_template(aws, fake_settings, tier)
        data = aws.ec2.describe_launch_template_versions(
            LaunchTemplateName=tier.lt_name)["LaunchTemplateVersions"][0]["LaunchTemplateData"]
    instance_tags = [spec for spec in data["TagSpecifications"] if spec["ResourceType"] == "instance"]
    assert instance_tags[0]["Tags"] == [{"Key": "Name", "Value": f"{tier_name}-app"}]


def test_delete_target_group_retries_while_the_listener_is_still_going_away():
    """Found on the real stack: DeleteTargetGroup can return ResourceInUse right after the ALB is deleted."""
    from botocore.exceptions import ClientError

    from stack.balancer import delete_target_group

    class FakeElbv2:
        def __init__(self):
            self.delete_calls = 0

        def describe_target_groups(self, Names):
            return {"TargetGroups": [{"TargetGroupArn": "arn:tg"}]}

        def delete_target_group(self, TargetGroupArn):
            self.delete_calls += 1
            if self.delete_calls < 3:
                raise ClientError({"Error": {"Code": "ResourceInUse"}}, "DeleteTargetGroup")

    class FakeAws:
        elbv2 = FakeElbv2()

    aws = FakeAws()
    delete_target_group(aws, "t-uploader-tg", sleep=lambda _: None)
    assert aws.elbv2.delete_calls == 3
