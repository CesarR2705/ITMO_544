"""User-data and launch templates."""
from __future__ import annotations

import base64
import logging

from botocore.exceptions import ClientError

from .clients import AwsClients
from .config import Settings, Tier
from .network import StackError
from .util import error_code

log = logging.getLogger("stack")

USER_DATA_LIMIT = 16 * 1024  # EC2 refuses more than 16 KB
RDS_CA_URL = "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"


def _b64_file(path) -> str:
    """Return a file's contents as base64 text."""
    return base64.b64encode(path.read_bytes()).decode()


def weather_environment(settings: Settings, db_host: str) -> list[str]:
    """Names and addresses only. The password is read from SSM at run time."""
    return [
        f'Environment="NWS_USER_AGENT=(itmo-444-544 weather lab, {settings.contact_email})"',
        f"Environment=DB_HOST={db_host}",
        f"Environment=DB_PORT={settings.db_port}",
        f"Environment=DB_NAME={settings.db_name}",
        f"Environment=DB_USER={settings.db_user}",
        f"Environment=DB_PASSWORD_PARAM={settings.db_password_param}",
        f"Environment=CACHE_SECONDS={settings.cache_seconds}",
    ]


def advisor_environment(settings: Settings, alb_dns: str) -> list[str]:
    """The advisor reaches the weather tier through the ALB, so the ALB must exist first."""
    return [
        f"Environment=WEATHER_URL=http://{alb_dns}:{settings.weather.listener_port}",
        f"Environment=GEMINI_KEY_PARAM={settings.gemini_param_name}",
        f"Environment=GEMINI_MODEL={settings.gemini_model}",
        f"Environment=KEY_CACHE_SECONDS={settings.key_cache_seconds}",
    ]


def weather_setup() -> list[str]:
    """The psql client for your own queries, and the bundle the app verifies RDS against."""
    return ["dnf install -y postgresql15", f"curl -sS -o /opt/app/rds-ca.pem {RDS_CA_URL}"]


def build_user_data(settings: Settings, tier: Tier, environment: list[str],
                    setup: list[str] | None = None) -> str:
    """The boot script: write the app files, install Node, run the app as a service."""
    app_js = _b64_file(tier.app_dir / "app.js")
    package_json = _b64_file(tier.app_dir / "package.json")
    setup_lines = "\n".join(setup or [])
    environment_lines = "\n".join(environment)
    script = f"""#!/bin/bash
dnf update -y
dnf install -y nodejs
mkdir -p /opt/app
{setup_lines}
echo "{app_js}" | base64 -d > /opt/app/app.js
echo "{package_json}" | base64 -d > /opt/app/package.json
cd /opt/app
npm install --omit=dev
cat > /etc/systemd/system/{tier.service_name}.service << 'SERVICE'
[Unit]
Description={tier.name.capitalize()} App
After=network.target

[Service]
Environment=PORT={settings.app_port}
Environment=AWS_REGION={settings.region}
{environment_lines}
WorkingDirectory=/opt/app
ExecStart=/usr/bin/node /opt/app/app.js
Restart=always
User=ec2-user

[Install]
WantedBy=multi-user.target
SERVICE
chown -R ec2-user:ec2-user /opt/app
systemctl daemon-reload
systemctl enable {tier.service_name}.service
systemctl start {tier.service_name}.service
"""
    if len(script.encode()) > USER_DATA_LIMIT:
        raise StackError(f"{tier.name} user-data is over the {USER_DATA_LIMIT} byte limit.")
    return script


def build_tier_user_data(settings: Settings, tier: Tier, alb_dns: str, db_host: str) -> str:
    """Return the boot script for one tier, with that tier's settings."""
    if tier.name == "weather":
        return build_user_data(settings, tier, weather_environment(settings, db_host), weather_setup())
    return build_user_data(settings, tier, advisor_environment(settings, alb_dns))


def launch_template_data(settings: Settings, tier: Tier, user_data: str) -> dict:
    """Return the launch template settings for one tier."""
    return {
        "ImageId": settings.ami_id,
        "InstanceType": settings.instance_type,
        "KeyName": settings.key_name,
        "SecurityGroupIds": [settings.app_sg_id],
        "IamInstanceProfile": {"Name": tier.profile_name},
        # The API wants user-data already base64 encoded.
        "UserData": base64.b64encode(user_data.encode()).decode(),
        "TagSpecifications": [{
            "ResourceType": "instance",
            "Tags": [{"Key": "Name", "Value": f"{tier.name}-app"}],
        }],
    }


def launch_template_exists(aws: AwsClients, tier: Tier) -> bool:
    """Return True if the tier's launch template exists."""
    try:
        aws.ec2.describe_launch_templates(LaunchTemplateNames=[tier.lt_name])
        return True
    except ClientError as err:
        if error_code(err) != "InvalidLaunchTemplateName.NotFoundException":
            raise
        return False


def ensure_launch_template(aws: AwsClients, settings: Settings, tier: Tier, user_data: str) -> int:
    """Create the template, or publish a new version if it already exists."""
    data = launch_template_data(settings, tier, user_data)
    if not launch_template_exists(aws, tier):
        aws.ec2.create_launch_template(LaunchTemplateName=tier.lt_name, LaunchTemplateData=data)
        log.info("Created launch template %s", tier.lt_name)
        return 1
    response = aws.ec2.create_launch_template_version(
        LaunchTemplateName=tier.lt_name, SourceVersion="1", LaunchTemplateData=data)
    version = response["LaunchTemplateVersion"]["VersionNumber"]
    log.info("Template %s exists, published version %s", tier.lt_name, version)
    return version


def delete_launch_template(aws: AwsClients, tier: Tier) -> None:
    """Delete the tier's launch template if it exists."""
    if launch_template_exists(aws, tier):
        aws.ec2.delete_launch_template(LaunchTemplateName=tier.lt_name)
        log.info("Deleted launch template %s", tier.lt_name)
