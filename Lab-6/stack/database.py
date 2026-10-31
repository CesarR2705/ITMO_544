"""The PostgreSQL database: private, encrypted, single-zone, no backups, and fully deletable."""
from __future__ import annotations

import logging
import time

from botocore.exceptions import ClientError

from . import network, parameters
from .clients import AwsClients
from .config import Settings
from .outputs import DatabaseOutputs
from .util import error_code, ignore_errors, retry_on

log = logging.getLogger("stack")

# Delay and attempts for the RDS waiters: 30 seconds for up to 30 minutes.
WAIT = {"Delay": 30, "MaxAttempts": 60}


def find_db_instance(aws: AwsClients, instance_id: str) -> dict | None:
    """Return the database description, or None if it does not exist."""
    try:
        return aws.rds.describe_db_instances(DBInstanceIdentifier=instance_id)["DBInstances"][0]
    except ClientError as err:
        if error_code(err) not in ("DBInstanceNotFound", "DBInstanceNotFoundFault"):
            raise
        return None


def ensure_subnet_group(aws: AwsClients, settings: Settings, subnets: list[str]) -> None:
    """Create the DB subnet group unless it already exists."""
    with ignore_errors("DBSubnetGroupAlreadyExists", "DBSubnetGroupAlreadyExistsFault"):
        aws.rds.create_db_subnet_group(
            DBSubnetGroupName=settings.db_subnet_group_name,
            DBSubnetGroupDescription="Lab subnets for the weather database",
            SubnetIds=subnets,
        )
        log.info("Created DB subnet group %s", settings.db_subnet_group_name)


def create_instance_request(settings: Settings, sg_id: str, password: str) -> dict:
    """Every setting of the database in one place. Never log what this returns."""
    return {
        "DBInstanceIdentifier": settings.db_instance_id,
        "DBInstanceClass": settings.db_instance_class,
        "Engine": "postgres",
        "AllocatedStorage": settings.db_allocated_storage,
        "StorageType": "gp2",
        "StorageEncrypted": True,
        "MasterUsername": settings.db_user,
        "MasterUserPassword": password,
        "DBName": settings.db_name,
        "Port": settings.db_port,
        "DBSubnetGroupName": settings.db_subnet_group_name,
        "VpcSecurityGroupIds": [sg_id],
        "AvailabilityZone": settings.az_a,
        "BackupRetentionPeriod": 0,
        "MultiAZ": False,
        "PubliclyAccessible": False,
        "AutoMinorVersionUpgrade": False,
        "DeletionProtection": False,
    }


def delete_instance_request(settings: Settings) -> dict:
    """No final snapshot and no kept backups, so nothing is left to keep costing money."""
    return {
        "DBInstanceIdentifier": settings.db_instance_id,
        "SkipFinalSnapshot": True,
        "DeleteAutomatedBackups": True,
    }


def ensure_db_instance(aws: AwsClients, settings: Settings, sg_id: str) -> None:
    """Create the database unless it already exists."""
    if find_db_instance(aws, settings.db_instance_id):
        log.info("Database %s already exists, skipping.", settings.db_instance_id)
        return
    password = parameters.read_secret(aws, settings.db_password_param)
    aws.rds.create_db_instance(**create_instance_request(settings, sg_id, password))
    log.info("Asked RDS to create %s", settings.db_instance_id)


def create_database(settings: Settings, aws: AwsClients) -> DatabaseOutputs:
    """Build everything the database needs and wait until it is available."""
    log.info("== Default VPC and subnets in both AZs ==")
    vpc_id = network.default_vpc_id(aws)
    subnets = [network.subnet_in_az(aws, vpc_id, az) for az in (settings.az_a, settings.az_b)]

    log.info("== Database security group ==")
    sg_id = network.ensure_db_security_group(aws, settings, vpc_id)

    log.info("== DB subnet group ==")
    ensure_subnet_group(aws, settings, subnets)

    log.info("== Database password (random, never printed) ==")
    parameters.ensure_random_password(aws, settings.db_password_param)

    log.info("== The PostgreSQL instance ==")
    ensure_db_instance(aws, settings, sg_id)
    log.info("Waiting for the database to become available (usually 5 to 10 minutes)...")
    aws.rds.get_waiter("db_instance_available").wait(
        DBInstanceIdentifier=settings.db_instance_id, WaiterConfig=WAIT)
    instance = find_db_instance(aws, settings.db_instance_id)
    return DatabaseOutputs(db_host=instance["Endpoint"]["Address"], db_security_group_id=sg_id)


def delete_db_instance(aws: AwsClients, settings: Settings) -> None:
    """Delete the database, if there is one, and wait until it is gone."""
    instance = find_db_instance(aws, settings.db_instance_id)
    if not instance:
        log.info("Database %s not found, nothing to delete.", settings.db_instance_id)
        return
    if instance["DBInstanceStatus"] != "deleting":  # a second run can find it still going
        aws.rds.delete_db_instance(**delete_instance_request(settings))
    log.info("Waiting for the database to be deleted (a few minutes)...")
    aws.rds.get_waiter("db_instance_deleted").wait(
        DBInstanceIdentifier=settings.db_instance_id, WaiterConfig=WAIT)


def delete_subnet_group(aws: AwsClients, settings: Settings, sleep=time.sleep) -> None:
    # Found the same way as the target group: the instance's "gone" can beat the group's release.
    """Delete the DB subnet group, retrying while the database releases it."""
    with ignore_errors("DBSubnetGroupNotFoundFault", "DBSubnetGroupNotFound"):
        retry_on({"InvalidDBSubnetGroupStateFault"},
                 lambda: aws.rds.delete_db_subnet_group(
                     DBSubnetGroupName=settings.db_subnet_group_name),
                 attempts=10, delay=15, sleep=sleep)
        log.info("Deleted DB subnet group %s", settings.db_subnet_group_name)


def delete_database(settings: Settings, aws: AwsClients, sleep=time.sleep) -> None:
    """Delete by name, not by saved state, so it still works after a half-finished create."""
    log.info("== The database (no final snapshot, no kept backups) ==")
    delete_db_instance(aws, settings)

    log.info("== DB subnet group ==")
    delete_subnet_group(aws, settings, sleep=sleep)

    log.info("== Database security group ==")
    sg_id = network.find_security_group(aws, settings.db_sg_name, network.default_vpc_id(aws))
    if sg_id:
        network.delete_security_group(aws, sg_id, sleep=sleep)

    log.info("== Database password parameter ==")
    parameters.delete_parameter(aws, settings.db_password_param)
    DatabaseOutputs.remove()
    log.info("Database removed.")


def leftovers(aws: AwsClients) -> dict[str, list[str]]:
    """Anything RDS would keep charging for. Every list should be empty after a delete."""
    return {
        "instances": [d["DBInstanceIdentifier"]
                      for d in aws.rds.describe_db_instances()["DBInstances"]],
        "snapshots": [s["DBSnapshotIdentifier"]
                      for s in aws.rds.describe_db_snapshots()["DBSnapshots"]],
        "automated backups": [
            b["DBInstanceIdentifier"] for b in
            aws.rds.describe_db_instance_automated_backups()["DBInstanceAutomatedBackups"]],
    }
