"""IAM policy documents as plain Python dictionaries.

Keeping them as pure functions means we can test them without touching AWS.
"""
from __future__ import annotations


def trust_policy() -> dict:
    """Who may assume the role: the EC2 service, nobody else."""
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "ec2.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    }


def parameter_arn(region: str, account_id: str, name: str) -> str:
    """A parameter called /a/b has the ARN ...:parameter/a/b, with one slash."""
    return f"arn:aws:ssm:{region}:{account_id}:parameter/{name.lstrip('/')}"


def read_one_secret_policy(arn: str) -> dict:
    """Read exactly one SSM parameter and nothing else."""
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": ["ssm:GetParameter"],
            "Resource": arn,
        }],
    }
