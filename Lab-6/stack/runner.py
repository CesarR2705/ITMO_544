"""The two entry points for the app tiers: build them, and tear them down."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from . import balancer, compute, identity, network, parameters, scaling
from .clients import AwsClients
from .config import Settings
from .network import StackError
from .outputs import DatabaseOutputs, StackOutputs

log = logging.getLogger("stack")


def check_prerequisites(settings: Settings, aws: AwsClients, directory: str | Path = ".") -> DatabaseOutputs:
    """Stop early, with a message that says what to run, if a dependency is missing."""
    if "replace-with-your-email" in settings.contact_email:
        raise StackError("Set CONTACT_EMAIL in .env to an address you own.")
    if not parameters.parameter_exists(aws, settings.gemini_param_name):
        raise StackError(f"Parameter {settings.gemini_param_name} was not found. "
                         "Run python store_gemini_key.py first.")
    try:
        return DatabaseOutputs.load(directory)
    except FileNotFoundError:
        raise StackError("db_outputs.json was not found. Run python create_database.py first.") from None


def create_weather_stack(settings: Settings, aws: AwsClients, directory: str | Path = ".",
                         iam_wait: int = 15, sleep=time.sleep) -> StackOutputs:
    """Build both tiers in order: IAM, network, ALB, launch templates, ASGs."""
    log.info("== Checking the Gemini key and the database ==")
    database = check_prerequisites(settings, aws, directory)

    log.info("== IAM roles and instance profiles ==")
    account_id = aws.account_id()
    for tier in settings.tiers:
        identity.ensure_role_and_profile(aws, settings, tier, account_id)
    log.info("Waiting %ss for IAM propagation...", iam_wait)
    sleep(iam_wait)

    log.info("== Default VPC and subnets in both AZs ==")
    vpc_id = network.default_vpc_id(aws)
    subnet_a = network.subnet_in_az(aws, vpc_id, settings.az_a)
    subnet_b = network.subnet_in_az(aws, vpc_id, settings.az_b)

    log.info("== Security groups ==")
    alb_sg_id = network.ensure_alb_security_group(aws, settings, vpc_id)
    network.restrict_app_security_group(aws, settings, alb_sg_id)

    log.info("== Target groups and the load balancer (the ALB comes first this time) ==")
    tg_arns = {tier.name: balancer.ensure_target_group(aws, settings, tier, vpc_id)
               for tier in settings.tiers}
    alb_arn, alb_dns = balancer.ensure_load_balancer(aws, settings, [subnet_a, subnet_b], alb_sg_id)
    for tier in settings.tiers:
        balancer.ensure_listener(aws, alb_arn, tier.listener_port, tg_arns[tier.name])

    log.info("== Launch templates (the advisor needs the ALB address) ==")
    for tier in settings.tiers:
        user_data = compute.build_tier_user_data(settings, tier, alb_dns, database.db_host)
        compute.ensure_launch_template(aws, settings, tier, user_data)

    log.info("== Auto Scaling Groups (these launch the instances) ==")
    for tier in settings.tiers:
        scaling.ensure_asg(aws, tier, tg_arns[tier.name], [subnet_a, subnet_b])

    return StackOutputs(
        vpc_id=vpc_id, subnet_a=subnet_a, subnet_b=subnet_b,
        alb_security_group_id=alb_sg_id, alb_arn=alb_arn, alb_dns_name=alb_dns,
        weather_tg_arn=tg_arns["weather"], advisor_tg_arn=tg_arns["advisor"],
    )


def delete_weather_stack(settings: Settings, aws: AwsClients, sleep=time.sleep) -> None:
    """Delete by name, not by saved state, so it still works after a half-finished create.

    The database and the Gemini key are left alone. They have their own delete steps.
    """
    log.info("== Auto Scaling Groups (this also terminates their instances) ==")
    for tier in settings.tiers:
        scaling.delete_asg(aws, tier.asg_name, sleep=sleep)

    log.info("== Load balancer and target groups ==")
    balancer.delete_load_balancer(aws, settings.alb_name)
    for tier in settings.tiers:
        balancer.delete_target_group(aws, tier.tg_name, sleep=sleep)

    log.info("== Security groups ==")
    vpc_id = network.default_vpc_id(aws)
    alb_sg_id = network.find_security_group(aws, settings.alb_sg_name, vpc_id)
    network.restore_app_security_group(aws, settings, alb_sg_id)
    if alb_sg_id:
        network.delete_security_group(aws, alb_sg_id, sleep=sleep)

    log.info("== Launch templates and IAM ==")
    for tier in settings.tiers:
        compute.delete_launch_template(aws, tier)
        identity.delete_role_and_profile(aws, tier)
    StackOutputs.remove()
    log.info("Weather stack removed. The Gemini key parameter and the database were left in place.")
