[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ScriptPath,
    [string]$SaveOutput
)
$ErrorActionPreference = 'Stop'
# AWS CLI on Korean Windows otherwise writes remote Unicode text through cp949.
$env:AWS_CLI_OUTPUT_ENCODING = 'utf-8'
$env:AWS_CLI_FILE_ENCODING = 'utf-8'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$projectRoot = Split-Path $PSScriptRoot -Parent
$state = Get-Content -Raw -LiteralPath (Join-Path $projectRoot '.local\deployment.json') | ConvertFrom-Json
$script = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $ScriptPath)).Replace("`r`n","`n")
$payload = @{commands=@($script);executionTimeout=@('900')} | ConvertTo-Json -Depth 4
$parametersPath = Join-Path $projectRoot '.local\ssm-parameters.json'
[IO.File]::WriteAllText($parametersPath,$payload,[Text.UTF8Encoding]::new($false))
$result = aws ssm send-command --profile $state.Profile --region $state.Region --instance-ids $state.InstanceId --document-name AWS-RunShellScript --parameters ('file://' + $parametersPath) --output json --no-cli-pager | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'SSM send-command failed' }
$commandId = $result.Command.CommandId
Write-Output "SSM command: $commandId"
for ($attempt = 0; $attempt -lt 180; $attempt++) {
    Start-Sleep -Seconds 3
    $rawInvocation = aws ssm get-command-invocation --profile $state.Profile --region $state.Region --command-id $commandId --instance-id $state.InstanceId --output json --no-cli-pager
    if ($LASTEXITCODE -ne 0) { continue }
    $invocation = $rawInvocation -join "`n" | ConvertFrom-Json
    if ($invocation.Status -in @('Pending','InProgress','Delayed')) { continue }
    if ($SaveOutput) {
        [IO.File]::WriteAllText($SaveOutput,$invocation.StandardOutputContent,[Text.UTF8Encoding]::new($false))
        Write-Output 'Output saved privately.'
    } else {
        Write-Output $invocation.StandardOutputContent
        Write-Output $invocation.StandardErrorContent
    }
    if ($invocation.Status -ne 'Success') { throw "SSM command status: $($invocation.Status)" }
    exit 0
}
throw 'SSM command did not finish before the local wait limit.'
