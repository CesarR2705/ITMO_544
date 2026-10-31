"""SSM Parameter Store: the only place the two secrets live.

Nothing in this module logs a value. Log the parameter's name, never what it holds.
"""
from __future__ import annotations

import logging
import secrets

from botocore.exceptions import ClientError

from .clients import AwsClients
from .util import error_code, ignore_errors

log = logging.getLogger("stack")


def parameter_exists(aws: AwsClients, name: str) -> bool:
    """Return True if the parameter exists, without reading its value."""
    try:
        aws.ssm.get_parameter(Name=name)
        return True
    except ClientError as err:
        if error_code(err) != "ParameterNotFound":
            raise
        return False


def put_secret(aws: AwsClients, name: str, value: str) -> None:
    """Store a value as a SecureString, replacing any earlier value."""
    aws.ssm.put_parameter(Name=name, Type="SecureString", Value=value, Overwrite=True)


def read_secret(aws: AwsClients, name: str) -> str:
    """Return the decrypted value. Never log what this returns."""
    return aws.ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]


def ensure_random_password(aws: AwsClients, name: str) -> None:
    """Generate the password once. A second run keeps it, so it still matches the database."""
    if parameter_exists(aws, name):
        log.info("Password parameter %s already exists, keeping it.", name)
        return
    put_secret(aws, name, secrets.token_hex(16))
    log.info("Stored a new random password in %s", name)


def delete_parameter(aws: AwsClients, name: str) -> None:
    """Delete the parameter if it exists."""
    with ignore_errors("ParameterNotFound"):
        aws.ssm.delete_parameter(Name=name)
        log.info("Deleted parameter %s", name)
