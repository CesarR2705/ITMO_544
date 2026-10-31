"""Default VPC, subnets, and the three security groups."""
from __future__ import annotations

import logging
import time

from .clients import AwsClients
from .config import Settings
from .util import ignore_errors, retry_on

log = logging.getLogger("stack")


class StackError(Exception):
    """Something the lab cannot continue without (for example, no subnet in an AZ)."""


def default_vpc_id(aws: AwsClients) -> str:
    """Return the ID of the default VPC, or raise StackError."""
    vpcs = aws.ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
    if not vpcs:
        raise StackError("No default VPC found in this region.")
    return vpcs[0]["VpcId"]


def subnet_in_az(aws: AwsClients, vpc_id: str, az: str) -> str:
    """Return a default subnet in this zone, or raise StackError."""
    subnets = aws.ec2.describe_subnets(Filters=[
        {"Name": "vpc-id", "Values": [vpc_id]},
        {"Name": "availability-zone", "Values": [az]},
    ])["Subnets"]
    if not subnets:
        raise StackError(f"The default VPC has no subnet in {az}.")
    return subnets[0]["SubnetId"]


def _cidr_rule(port: int, cidr: str = "0.0.0.0/0") -> list[dict]:
    """Return an ingress rule that opens a port to a CIDR range."""
    return [{"IpProtocol": "tcp", "FromPort": port, "ToPort": port,
             "IpRanges": [{"CidrIp": cidr}]}]


def _group_rule(port: int, group_id: str) -> list[dict]:
    """Return an ingress rule that opens a port to a security group."""
    return [{"IpProtocol": "tcp", "FromPort": port, "ToPort": port,
             "UserIdGroupPairs": [{"GroupId": group_id}]}]


def find_security_group(aws: AwsClients, name: str, vpc_id: str) -> str | None:
    """Return the ID of the named group in this VPC, or None."""
    groups = aws.ec2.describe_security_groups(Filters=[
        {"Name": "group-name", "Values": [name]},
        {"Name": "vpc-id", "Values": [vpc_id]},
    ])["SecurityGroups"]
    return groups[0]["GroupId"] if groups else None


def ensure_alb_security_group(aws: AwsClients, settings: Settings, vpc_id: str) -> str:
    """Return the ALB group's ID, creating it and opening both listener ports."""
    group_id = find_security_group(aws, settings.alb_sg_name, vpc_id)
    if group_id is None:
        group_id = aws.ec2.create_security_group(
            GroupName=settings.alb_sg_name,
            Description="Allow inbound to the ALB on the app listener ports",
            VpcId=vpc_id,
        )["GroupId"]
        log.info("Created ALB security group %s", group_id)
    for tier in settings.tiers:
        with ignore_errors("InvalidPermission.Duplicate"):
            aws.ec2.authorize_security_group_ingress(
                GroupId=group_id, IpPermissions=_cidr_rule(tier.listener_port))
    return group_id


def restrict_app_security_group(aws: AwsClients, settings: Settings, alb_sg_id: str) -> None:
    """Replace 'port 3000 open to the world' with 'port 3000 open to the ALB only'."""
    with ignore_errors("InvalidPermission.NotFound"):
        aws.ec2.revoke_security_group_ingress(
            GroupId=settings.app_sg_id, IpPermissions=_cidr_rule(settings.app_port))
    with ignore_errors("InvalidPermission.Duplicate"):
        aws.ec2.authorize_security_group_ingress(
            GroupId=settings.app_sg_id, IpPermissions=_group_rule(settings.app_port, alb_sg_id))


def restore_app_security_group(aws: AwsClients, settings: Settings, alb_sg_id: str | None) -> None:
    """Put back the open port 3000 rule that the stack replaced."""
    if alb_sg_id:
        with ignore_errors("InvalidPermission.NotFound"):
            aws.ec2.revoke_security_group_ingress(
                GroupId=settings.app_sg_id, IpPermissions=_group_rule(settings.app_port, alb_sg_id))
    with ignore_errors("InvalidPermission.Duplicate"):
        aws.ec2.authorize_security_group_ingress(
            GroupId=settings.app_sg_id, IpPermissions=_cidr_rule(settings.app_port))


def ensure_db_security_group(aws: AwsClients, settings: Settings, vpc_id: str) -> str:
    """Port 5432 from the app security group only. A source group, never a CIDR range."""
    group_id = find_security_group(aws, settings.db_sg_name, vpc_id)
    if group_id is None:
        group_id = aws.ec2.create_security_group(
            GroupName=settings.db_sg_name,
            Description="PostgreSQL access from the lab app instances only",
            VpcId=vpc_id,
        )["GroupId"]
        log.info("Created database security group %s", group_id)
    allow_app_to_database(aws, settings, group_id)
    return group_id


def allow_app_to_database(aws: AwsClients, settings: Settings, db_sg_id: str) -> None:
    """Let the app security group reach the database port."""
    with ignore_errors("InvalidPermission.Duplicate"):
        aws.ec2.authorize_security_group_ingress(
            GroupId=db_sg_id, IpPermissions=_group_rule(settings.db_port, settings.app_sg_id))


def block_app_from_database(aws: AwsClients, settings: Settings, db_sg_id: str) -> None:
    """Remove the app security group's access to the database port."""
    with ignore_errors("InvalidPermission.NotFound"):
        aws.ec2.revoke_security_group_ingress(
            GroupId=db_sg_id, IpPermissions=_group_rule(settings.db_port, settings.app_sg_id))


def delete_security_group(aws: AwsClients, group_id: str, sleep=time.sleep) -> None:
    # Network interfaces can linger for a minute after a load balancer or database is deleted.
    """Delete a group, retrying while its network interfaces are released."""
    with ignore_errors("InvalidGroup.NotFound"):
        retry_on({"DependencyViolation"},
                 lambda: aws.ec2.delete_security_group(GroupId=group_id),
                 attempts=10, delay=15, sleep=sleep)
        log.info("Deleted security group %s", group_id)
