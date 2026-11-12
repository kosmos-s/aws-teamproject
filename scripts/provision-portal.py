"""Explicitly approved RDS/S3 lab deployment; uses the operator's AWS CLI login.

Run from the repository root. Private state and request bodies stay in .local.
Never prints secret values. Does not alter the existing EC2 stop deadline.
"""
import json
import os
import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".local"
STATE = json.loads((PRIVATE / "deployment.json").read_text(encoding="utf-8-sig"))


def aws(service, operation, payload=None):
    command = ["aws", service, operation, "--profile", STATE["Profile"], "--region", STATE["Region"], "--output", "json", "--no-cli-pager"]
    request = PRIVATE / "portal-aws-request.json"
    if payload:
        request.write_text(json.dumps(payload), encoding="utf-8")
        command += ["--cli-input-json", "file://" + str(request)]
    env = dict(os.environ, AWS_CLI_OUTPUT_ENCODING="utf-8", AWS_CLI_FILE_ENCODING="utf-8")
    try:
        result = subprocess.run(command, capture_output=True, env=env)
        if result.returncode:
            # API error messages can echo request identifiers; keep the detail private.
            (PRIVATE / "portal-aws-error.txt").write_bytes(result.stderr)
            raise RuntimeError(f"{service} {operation} failed; inspect private error file")
        return json.loads(result.stdout.decode("utf-8-sig") or "{}")
    finally:
        request.unlink(missing_ok=True)


def main():
    state_path = PRIVATE / "portal-cloud.json"
    if state_path.exists():
        print("Portal cloud state exists; inspect before re-running. No duplicate resources created.")
        return
    account = aws("sts", "get-caller-identity")["Account"]
    instance = aws("ec2", "describe-instances", {"InstanceIds": [STATE["InstanceId"]]})["Reservations"][0]["Instances"][0]
    vpc = instance["VpcId"]
    subnets = aws("ec2", "describe-subnets", {"Filters": [{"Name": "vpc-id", "Values": [vpc]}]})["Subnets"]
    identifier = "kosmos-orca-portal"
    if any(db["DBInstanceIdentifier"] == identifier for db in aws("rds", "describe-db-instances")["DBInstances"]):
        raise RuntimeError("Existing DB found without local state; inspect before creating")
    cloud = {"db": identifier, "bucket": "kosmos-orca-portal-" + secrets.token_hex(6), "parameter": "/kosmos/portal/bootstrap", "StopAt": STATE["StopAt"]}
    state_path.write_text(json.dumps(cloud, indent=2), encoding="utf-8")
    sg = aws("ec2", "create-security-group", {"GroupName": "kosmos-orca-portal-db", "Description": "Portal database from existing EC2 security group only", "VpcId": vpc})["GroupId"]
    cloud["db_sg"] = sg
    state_path.write_text(json.dumps(cloud, indent=2), encoding="utf-8")
    aws("ec2", "authorize-security-group-ingress", {"GroupId": sg, "IpPermissions": [{"IpProtocol": "tcp", "FromPort": 3306, "ToPort": 3306, "UserIdGroupPairs": [{"GroupId": STATE["SecurityGroupId"]}]}]})
    aws("rds", "create-db-subnet-group", {"DBSubnetGroupName": "kosmos-orca-portal", "DBSubnetGroupDescription": "Existing VPC subnets for private portal RDS", "SubnetIds": [s["SubnetId"] for s in subnets]})
    master = secrets.token_urlsafe(30)
    aws("ssm", "put-parameter", {"Name": cloud["parameter"], "Type": "SecureString", "Value": json.dumps({"username": "portalowner", "password": master, "db": identifier}), "Overwrite": False})
    aws("rds", "create-db-instance", {"DBInstanceIdentifier": identifier, "DBName": "kosmos", "Engine": "mysql", "EngineVersion": "8.4.13", "DBInstanceClass": "db.t4g.micro", "AllocatedStorage": 20, "StorageType": "gp3", "StorageEncrypted": True, "MasterUsername": "portalowner", "MasterUserPassword": master, "DBSubnetGroupName": "kosmos-orca-portal", "VpcSecurityGroupIds": [sg], "PubliclyAccessible": False, "MultiAZ": False, "BackupRetentionPeriod": 1, "AutoMinorVersionUpgrade": True, "CopyTagsToSnapshot": True, "EnablePerformanceInsights": False, "MonitoringInterval": 0, "Tags": [{"Key": "Project", "Value": "kosmos-orca"}]})
    s3 = {"Bucket": cloud["bucket"]}
    aws("s3api", "create-bucket", {**s3, "CreateBucketConfiguration": {"LocationConstraint": STATE["Region"]}, "ObjectOwnership": "BucketOwnerEnforced"})
    aws("s3api", "put-public-access-block", {**s3, "PublicAccessBlockConfiguration": {key: True for key in ["BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"]}})
    aws("s3api", "put-bucket-encryption", {**s3, "ServerSideEncryptionConfiguration": {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}})
    aws("s3api", "put-bucket-lifecycle-configuration", {**s3, "LifecycleConfiguration": {"Rules": [{"ID": "expire-lab-backups", "Status": "Enabled", "Filter": {"Prefix": "backups/"}, "Expiration": {"Days": 3}, "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1}}]}})
    bucket_arn = "arn:aws:s3:::" + cloud["bucket"]
    policy = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"], "Resource": [bucket_arn + "/attachments/*", bucket_arn + "/backups/*"]},
        {"Effect": "Allow", "Action": "ssm:GetParameter", "Resource": f"arn:aws:ssm:{STATE['Region']}:{account}:parameter{cloud['parameter']}"},
        {"Effect": "Allow", "Action": ["rds:StopDBInstance", "rds:DescribeDBInstances"], "Resource": f"arn:aws:rds:{STATE['Region']}:{account}:db:{identifier}"}]}
    aws("iam", "put-role-policy", {"RoleName": STATE["RoleName"], "PolicyName": "kosmos-portal-storage-db-stop", "PolicyDocument": json.dumps(policy)})
    cloud["status"] = "creating"
    state_path.write_text(json.dumps(cloud, indent=2), encoding="utf-8")
    print("Private RDS creation requested; encrypted private S3 and scoped EC2 role configured. Existing deadline unchanged.")


if __name__ == "__main__":
    main()
