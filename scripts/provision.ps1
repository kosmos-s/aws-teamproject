[CmdletBinding()]
param([string]$Profile = 'kosmos-cloud', [string]$Region = 'ap-northeast-2')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$localDir = Join-Path $projectRoot '.local'
New-Item -ItemType Directory -Path $localDir -Force | Out-Null
function Invoke-ProjectAws([string[]]$Arguments) {
    $raw = & aws @Arguments --profile $Profile --region $Region --output json --no-cli-pager
    if ($LASTEXITCODE -ne 0) { throw "AWS command failed: $($Arguments[0..1] -join ' ')" }
    if ($raw) { return ($raw -join "`n" | ConvertFrom-Json) }
}
$existing = Invoke-ProjectAws @('ec2','describe-instances','--filters','Name=tag:Project,Values=kosmos-orca-cloud','Name=instance-state-name,Values=pending,running,stopping,stopped')
$instances = @($existing.Reservations | ForEach-Object { $_.Instances })
if ($instances.Count -gt 0) { throw 'Existing project instance found; inspect .local/deployment.json and reuse it.' }
$plan = & aws freetier get-account-plan-state --profile $Profile --region us-east-1 --output json --no-cli-pager | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $plan.accountPlanType -ne 'FREE' -or $plan.accountPlanStatus -ne 'ACTIVE' -or $plan.accountPlanRemainingCredits.amount -lt 5) { throw 'Expected active Free plan with at least $5 credit.' }
$trust = @{Version='2012-10-17';Statement=@(@{Effect='Allow';Principal=@{Service='ec2.amazonaws.com'};Action='sts:AssumeRole'})}
$trustPath = Join-Path $localDir 'ec2-trust.json'
$trust | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $trustPath -Encoding utf8NoBOM
$roleName = 'kosmos-orca-ec2-ssm'
$null = Invoke-ProjectAws @('iam','create-role','--role-name',$roleName,'--assume-role-policy-document',('file://' + $trustPath),'--description','KOSMOS single EC2 SSM management only')
$null = Invoke-ProjectAws @('iam','attach-role-policy','--role-name',$roleName,'--policy-arn','arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore')
$null = Invoke-ProjectAws @('iam','create-instance-profile','--instance-profile-name',$roleName)
$null = Invoke-ProjectAws @('iam','add-role-to-instance-profile','--instance-profile-name',$roleName,'--role-name',$roleName)
$vpc = Invoke-ProjectAws @('ec2','describe-vpcs','--filters','Name=is-default,Values=true')
if (@($vpc.Vpcs).Count -ne 1) { throw 'Expected exactly one default VPC.' }
$subnets = Invoke-ProjectAws @('ec2','describe-subnets','--filters',('Name=vpc-id,Values=' + $vpc.Vpcs[0].VpcId),'Name=availability-zone,Values=ap-northeast-2a')
if (@($subnets.Subnets).Count -ne 1) { throw 'Expected one ap-northeast-2a default subnet.' }
$sg = Invoke-ProjectAws @('ec2','create-security-group','--group-name','kosmos-orca-ssm-only','--description','No inbound ports; access using IAM authenticated SSM forwarding','--vpc-id',$vpc.Vpcs[0].VpcId)
$tags = 'ResourceType=security-group,Tags=[{Key=Project,Value=kosmos-orca-cloud}]'
$null = Invoke-ProjectAws @('ec2','create-tags','--resources',$sg.GroupId,'--tags','Key=Project,Value=kosmos-orca-cloud')
$deadline = [DateTimeOffset]::UtcNow.AddHours(24)
$stopAt = $deadline.ToString('yyyy-MM-dd HH:mm:ss') + ' UTC'
$bootstrap = [IO.File]::ReadAllText((Join-Path $projectRoot 'deploy\bootstrap.sh')).Replace('__STOP_AT__',$stopAt).Replace("`r`n","`n")
$request = @{
    ImageId='ami-05b829d75c9f9183e';InstanceType='t3.small';MinCount=1;MaxCount=1
    ClientToken=[guid]::NewGuid().ToString();IamInstanceProfile=@{Name=$roleName}
    InstanceInitiatedShutdownBehavior='stop';CreditSpecification=@{CpuCredits='standard'}
    MetadataOptions=@{HttpTokens='required';HttpEndpoint='enabled';HttpPutResponseHopLimit=1}
    NetworkInterfaces=@(@{DeviceIndex=0;SubnetId=$subnets.Subnets[0].SubnetId;Groups=@($sg.GroupId);AssociatePublicIpAddress=$true;DeleteOnTermination=$true})
    BlockDeviceMappings=@(@{DeviceName='/dev/sda1';Ebs=@{VolumeSize=20;VolumeType='gp3';Encrypted=$true;DeleteOnTermination=$true}})
    UserData=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($bootstrap))
    TagSpecifications=@(@{ResourceType='instance';Tags=@(@{Key='Name';Value='kosmos-orca-cloud'},@{Key='Project';Value='kosmos-orca-cloud'},@{Key='ApprovedStopAt';Value=$deadline.ToString('o')})},@{ResourceType='volume';Tags=@(@{Key='Project';Value='kosmos-orca-cloud'})})
}
$requestPath = Join-Path $localDir 'run-instances.json'
$request | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $requestPath -Encoding utf8NoBOM
# Save the exact request and idempotency token before the mutation.
@{Profile=$Profile;Region=$Region;StopAt=$deadline.ToString('o');SecurityGroupId=$sg.GroupId;RoleName=$roleName;Status='prepared'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $localDir 'deployment.json') -Encoding utf8NoBOM
Start-Sleep -Seconds 12
$result = Invoke-ProjectAws @('ec2','run-instances','--cli-input-json',('file://' + $requestPath))
$state = @{Profile=$Profile;Region=$Region;InstanceId=$result.Instances[0].InstanceId;StopAt=$deadline.ToString('o');SecurityGroupId=$sg.GroupId;RoleName=$roleName;Status='launched'}
$state | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $localDir 'deployment.json') -Encoding utf8NoBOM
$state | ConvertTo-Json
