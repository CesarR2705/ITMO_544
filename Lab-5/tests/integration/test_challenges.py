"""Part J challenges that check the deployed stack (1 and 4)."""
import pytest

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("tier_name", ["uploader", "viewer"])
def test_launch_template_tags_instances_with_the_tier_name(aws, settings, tier_name):
    """Challenge 1: the latest template version tags every instance Name=<tier>-app."""
    tier = settings.tier(tier_name)
    data = aws.ec2.describe_launch_template_versions(
        LaunchTemplateName=tier.lt_name, Versions=["$Latest"])["LaunchTemplateVersions"][0]["LaunchTemplateData"]
    instance_tags = [spec for spec in data["TagSpecifications"] if spec["ResourceType"] == "instance"]
    assert {"Key": "Name", "Value": f"{tier_name}-app"} in instance_tags[0]["Tags"]


def test_ssh_is_not_open_to_the_world(aws, settings):
    """Challenge 4: drift check. Fails if anyone adds 0.0.0.0/0 on port 22 to the app SG."""
    group = aws.ec2.describe_security_groups(GroupIds=[settings.app_sg_id])["SecurityGroups"][0]
    for rule in group["IpPermissions"]:
        if rule.get("IpProtocol") == "-1":
            covers_22 = True
        else:
            covers_22 = rule.get("FromPort", 0) <= 22 <= rule.get("ToPort", 65535)
        if covers_22:
            cidrs = [r["CidrIp"] for r in rule.get("IpRanges", [])]
            assert "0.0.0.0/0" not in cidrs, f"port 22 is open to the world: {rule}"
