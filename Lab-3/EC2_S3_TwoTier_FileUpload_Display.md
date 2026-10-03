# EC2, S3 Two-Tier Architecture with File Upload and Display

## (1) Screenshot of your local lab03/uploader-app/ and lab03/viewer-app/ folders showing app.js and package.json in each.

![Screenshot 1](./Images/1st_SC.png)

## (2) Screenshot of the Uploader page and a successful upload confirmation.

![Screenshot 2](./Images/upload_SC.png)
![Screenshot 3](./Images/uploaded_SC.png)

## (3) Screenshot of attempting to upload a non- .txt file (e.g., a .jpg or .pdf ), showing the “only .txt files are allowed” error.

![Screenshot 4](./Images/upload_error_SC.png)

## (4) Screenshot of the Viewer page displaying the uploaded file’s content

![Screenshot 5](./Images/viewer_page_SC.png)

## (5) Screenshot of aws ec2 describe-launch-templates showing both templates.

![Screenshot 6](./Images/LT_SC.png)

## (6) Screenshot of aws ec2 describe-launch-template-versions --launch-template-name <uploader-lt-name> after re-running the create script twice, showing more than one version.

![Screenshot 7](./Images/LT_version_SC.png)

## (7) aws iam get-role-policy output (or screenshot) for both roles, showing each has only its one intended action on the exact shared.txt key.

![Screenshot 8](./Images/policies_SC.png)

## (8) Screenshot of create_app_stack.sh output showing both instances running with public IPs.

![Screenshot 9](./Images/create_stack_SC.png)

## (9) Screenshot of delete_app_stack.sh completing with no errors.

![Screenshot 10](./Images/delete_stack_SC.png)

## (10) One paragraph explaining why the uploader and viewer use separate IAM roles instead of one shared role with both permissions.

Using separate IAM roles for the uploader and viewer instances instead of a single shared role is a fundamental security practice in cloud architecture because it rasonates with the principle of least privilege. Each role attached to the specific instance is granted only the specific permissions required for the instance to perform its function, the uploader role has permission to upload files to the S3 bucket, while the viewer role has read permissions to read files from the S3 bucket. If a single role with both permissions were used, any instance running that role would have unnecessary access to delete or modify files it doesn't need to touch. This separation ensures that even if one instance is compromised, the potential damage is contained and limited to its specific permissions, reducing the overall attack surface and enhancing system security.

## (11) One or two sentences explaining why embedding code directly into user-data means the instance never needs a Git or S3 credential just to fetch its own code.

By embedding the application code directly into the instance's user-data, we eliminate the need for the instance to fetch its own code from a remote source like Git or S3. This approach ensures that the instance has immediate access to the necessary files upon launch, without requiring any additional credentials or network access.