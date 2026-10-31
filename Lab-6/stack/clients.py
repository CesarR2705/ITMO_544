"""One place that builds the boto3 clients the stack needs."""
from __future__ import annotations

from dataclasses import dataclass

import boto3


@dataclass
class AwsClients:
    """The boto3 clients, passed around so tests can run them against moto."""
    iam: object
    ec2: object
    elbv2: object
    autoscaling: object
    rds: object
    ssm: object
    sts: object

    @classmethod
    def create(cls, region: str) -> "AwsClients":
        """Build every client for one region."""
        session = boto3.session.Session(region_name=region)
        return cls(
            iam=session.client("iam"),
            ec2=session.client("ec2"),
            elbv2=session.client("elbv2"),
            autoscaling=session.client("autoscaling"),
            rds=session.client("rds"),
            ssm=session.client("ssm"),
            sts=session.client("sts"),
        )

    def account_id(self) -> str:
        """Return the ID of the AWS account these clients use."""
        return self.sts.get_caller_identity()["Account"]
