[CmdletBinding()]
param([int]$LocalPort = 6768)
$ErrorActionPreference = 'Stop'
if ($LocalPort -lt 1024 -or $LocalPort -gt 65535) { throw 'Use a port between 1024 and 65535.' }
$projectRoot = Split-Path $PSScriptRoot -Parent
$state = Get-Content -Raw -LiteralPath (Join-Path $projectRoot '.local\deployment.json') | ConvertFrom-Json
$pluginBin = Join-Path $projectRoot 'vendor\ssm\bin'
if (Test-Path -LiteralPath (Join-Path $pluginBin 'session-manager-plugin.exe')) { $env:PATH = $pluginBin + ';' + $env:PATH }
Write-Output "Keep this terminal open. Browser URL: http://127.0.0.1:$LocalPort/"
aws ssm start-session --profile $state.Profile --region $state.Region --target $state.InstanceId --document-name AWS-StartPortForwardingSession --parameters "portNumber=6768,localPortNumber=$LocalPort" --no-cli-pager
if ($LASTEXITCODE -ne 0) { throw 'SSM forwarding failed. Verify AWS login and instance status.' }
