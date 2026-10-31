# Weather Advisor in the Cloud: Two Tiers, a Free AI Model and a PostgreSQL Database

## What moto could not prove, and which integration test covers each gap

Moto proved that my code asks AWS for the right things: the database request has BackupRetentionPeriod=0, the rule names the app security group and no CIDR range, each role's policy names exactly one parameter, the ALB exists before the launch templates, and create and delete are safe to repeat. What it can't prove is that any of that behaves the way the request says, because moto stores what it is given and hands it back.

- **Real backups.** A retention of 0 in moto is only a saved number. No backup system exists there to turn off. test_real_database_has_no_backups_and_no_public_address asks real RDS for the setting, the snapshots, and the automated backups.
  
- **Real network reachability.** Moto stores security group rules but never enforces them, and PubliclyAccessible=False is only a flag. test_database_port_is_not_reachable_from_this_computer opens a real TCP connection to port 5432 and expects it to fail, and test_instances_answer_only_through_the_load_balancer does the same against port 3000 while the ALB answers 200.
  
- **TLS.** Moto has no database server, so there is no certificate to check. test_tls_certificate_verifies_against_the_rds_bundle runs psql on the weather instance with sslmode=verify-full and confirms the session is encrypted.
  
- **IAM enforcement.** Moto stores the policy text, and my unit test can only compare that text. test_each_role_can_read_only_its_own_secret asks AWS's own policy evaluator through simulate_principal_policy.
  
- **Whether anything actually runs.** Moto never boots an instance, so it can't show that user-data works, that npm install succeeds, or that the app connects to the database. test_every_target_becomes_healthy, test_second_lookup_is_a_miss_then_a_hit_and_lands_in_history and test_the_full_smoke_test_passes cover the whole path, including a real answer from Gemini.
  
- **Failure behavior.** Moto can't take a dependency away from a running app. test_forecast_survives_losing_the_database and test_advisor_fails_fast_while_the_weather_tier_recovers do it on the real stack.

## Python compared with bash for creating the database and waiting for it

The steps are the same, but the Python version was easier to get right because the failure handling is exact. The bash script hides every failure of create-db-subnet-group behind >/dev/null 2>&1 || echo "already exists", so a bad subnet ID or a missing permission prints the same reassuring message and the script carries on. In Python, ignore_errors("DBSubnetGroupAlreadyExists") lets only that one error through. Python also passes the password straight into the API call instead of on a command line, so it never appears in a process list, and it only reads the password when it is actually about to create the database. Testing is where the difference is largest. To test the bash script I would have to create a real database, wait about ten minutes, and pay for it. The Python runs against moto in seconds, create_instance_request is a plain function I can check field by field, and sleep is passed in so a test never waits. Bash was easier in one respect: aws rds wait db-instance-available is a single line, while boto3 needs a waiter object and a config for its delay and attempts.
