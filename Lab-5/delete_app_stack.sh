#!/bin/bash
set -e
export $(grep -v '^#' .env | xargs)
if [ -f stack_outputs.env ]; then
export $(grep -v '^#' stack_outputs.env | xargs)
else
echo "stack_outputs.env not found — looking resources up by name instead."
ALB_ARN=$(aws elbv2 describe-load-balancers --names "$ALB_NAME" --region "$AWS_REGION" \
--query "LoadBalancers[0].LoadBalancerArn" --output text 2>/dev/null || true)
UPLOADER_TG_ARN=$(aws elbv2 describe-target-groups --names "$UPLOADER_TG_NAME" --region "$AWS_REGION" \
--query "TargetGroups[0].TargetGroupArn" --output text 2>/dev/null || true)
VIEWER_TG_ARN=$(aws elbv2 describe-target-groups --names "$VIEWER_TG_NAME" --region "$AWS_REGION" \
--query "TargetGroups[0].TargetGroupArn" --output text 2>/dev/null || true)
ALB_SECURITY_GROUP_ID=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$ALB_SG_NAME" \
--query "SecurityGroups[0].GroupId" --output text --region "$AWS_REGION" 2>/dev/null || true)
fi

# --- New: tear down the ALB/ASG/multi-AZ layer first ---
echo "== Deleting Auto Scaling Groups (this also terminates their instances) =="
aws autoscaling delete-auto-scaling-group \
--auto-scaling-group-name "$UPLOADER_ASG_NAME" --force-delete --region "$AWS_REGION" 2>/dev/null || true
aws autoscaling delete-auto-scaling-group \
--auto-scaling-group-name "$VIEWER_ASG_NAME" --force-delete --region "$AWS_REGION" 2>/dev/null || true
echo "Waiting for both Auto Scaling Groups to be gone..."
for ASG_NAME in "$UPLOADER_ASG_NAME" "$VIEWER_ASG_NAME"; do
GONE=no
for i in $(seq 1 40); do
EXISTING=$(aws autoscaling describe-auto-scaling-groups \
--auto-scaling-group-names "$ASG_NAME" --region "$AWS_REGION" \
--query "AutoScalingGroups[0].AutoScalingGroupName" --output text 2>/dev/null || true)
if [ "$EXISTING" = "None" ] || [ -z "$EXISTING" ]; then
echo "$ASG_NAME deleted."
GONE=yes
break
fi
sleep 15
done
if [ "$GONE" = "no" ]; then
echo "$ASG_NAME still exists after 10 minutes — check the console."
fi
done

echo "== Deleting the load balancer =="
if [ -n "$ALB_ARN" ] && [ "$ALB_ARN" != "None" ]; then
aws elbv2 delete-load-balancer --load-balancer-arn "$ALB_ARN" --region "$AWS_REGION" 2>/dev/null || true
aws elbv2 wait load-balancers-deleted --load-balancer-arns "$ALB_ARN" --region "$AWS_REGION" 2>/dev/null || true
fi

echo "== Deleting target groups =="
# Target groups stay "in use" for a few seconds after the ALB is deleted, so retry
for TG_ARN in "$UPLOADER_TG_ARN" "$VIEWER_TG_ARN"; do
if [ -z "$TG_ARN" ] || [ "$TG_ARN" = "None" ]; then
continue
fi
for i in $(seq 1 6); do
if aws elbv2 delete-target-group --target-group-arn "$TG_ARN" --region "$AWS_REGION" 2>/dev/null; then
echo "Deleted target group ${TG_ARN##*targetgroup/}"
break
fi
echo "Target group still in use, retrying in 10s..."
sleep 10
done
done

echo "== Restoring the app security group to its previous-lab state =="
aws ec2 revoke-security-group-ingress --group-id "$APP_SECURITY_GROUP_ID" \
--protocol tcp --port 3000 --source-group "$ALB_SECURITY_GROUP_ID" --region "$AWS_REGION" >/dev/null 2>&1 || true
aws ec2 authorize-security-group-ingress --group-id "$APP_SECURITY_GROUP_ID" \
--protocol tcp --port 3000 --cidr 0.0.0.0/0 --region "$AWS_REGION" >/dev/null 2>&1 || true

echo "== Deleting the ALB security group =="
if [ -z "$ALB_SECURITY_GROUP_ID" ] || [ "$ALB_SECURITY_GROUP_ID" = "None" ]; then
echo "ALB security group not found, skipping."
else
for i in $(seq 1 6); do
if aws ec2 delete-security-group --group-id "$ALB_SECURITY_GROUP_ID" --region "$AWS_REGION" >/dev/null 2>&1; then
echo "ALB security group deleted."
break
fi
echo "ALB security group still in use (ALB network interfaces draining), retrying in 20s..."
sleep 20
done
fi

rm -f stack_outputs.env uploader-lt-data.json viewer-lt-data.json user-data-uploader.sh user-data-viewer.sh \
uploader-policy.json viewer-policy.json trust-policy.json

# --- Unchanged from the previous lab: launch templates + IAM + bucket teardown ---
echo "== Deleting launch templates =="
aws ec2 delete-launch-template --launch-template-name "$UPLOADER_LT_NAME" --region "$AWS_REGION" >/dev/null 2>&1 || true
aws ec2 delete-launch-template --launch-template-name "$VIEWER_LT_NAME" --region "$AWS_REGION" >/dev/null 2>&1 || true

echo "== Removing IAM instance profiles and roles =="
aws iam remove-role-from-instance-profile --instance-profile-name "$UPLOADER_PROFILE_NAME" \
--role-name "$UPLOADER_ROLE_NAME" 2>/dev/null || true
aws iam delete-instance-profile --instance-profile-name "$UPLOADER_PROFILE_NAME" 2>/dev/null || true
aws iam delete-role-policy --role-name "$UPLOADER_ROLE_NAME" \
--policy-name "${UPLOADER_ROLE_NAME}-policy" 2>/dev/null || true
aws iam delete-role --role-name "$UPLOADER_ROLE_NAME" 2>/dev/null || true
aws iam remove-role-from-instance-profile --instance-profile-name "$VIEWER_PROFILE_NAME" \
--role-name "$VIEWER_ROLE_NAME" 2>/dev/null || true
aws iam delete-instance-profile --instance-profile-name "$VIEWER_PROFILE_NAME" 2>/dev/null || true
aws iam delete-role-policy --role-name "$VIEWER_ROLE_NAME" \
--policy-name "${VIEWER_ROLE_NAME}-policy" 2>/dev/null || true
aws iam delete-role --role-name "$VIEWER_ROLE_NAME" 2>/dev/null || true

echo "== Emptying and deleting S3 bucket =="
aws s3 rm "s3://$BUCKET_NAME" --recursive --region "$AWS_REGION" 2>/dev/null || true
aws s3api delete-bucket --bucket "$BUCKET_NAME" --region "$AWS_REGION" 2>/dev/null || true
echo "Cleanup complete."
