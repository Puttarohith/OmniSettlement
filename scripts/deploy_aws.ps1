# OmniSettlement AWS Production Automated Deployment Script (PowerShell)
# Usage: .\scripts\deploy_aws.ps1 [-Region <region>]

param (
    [string]$Region = "us-east-1"
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  OMNISETTLEMENT - AWS PRODUCTION DEPLOYMENT ENGINE      " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Check AWS Credentials
if (-not $env:AWS_ACCESS_KEY_ID -and -not (Test-Path "$env:USERPROFILE\.aws\credentials")) {
    Write-Host ""
    Write-Host " [!] No AWS credentials found in environment or ~/.aws/credentials." -ForegroundColor Yellow
    Write-Host " Please provide your AWS credentials to proceed:" -ForegroundColor White
    
    $keyId = Read-Host " Enter AWS_ACCESS_KEY_ID"
    $secretKey = Read-Host " Enter AWS_SECRET_ACCESS_KEY" -AsSecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secretKey)
    $plainSecret = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    
    $env:AWS_ACCESS_KEY_ID = $keyId.Trim()
    $env:AWS_SECRET_ACCESS_KEY = $plainSecret.Trim()
    $env:AWS_DEFAULT_REGION = $Region
}

Write-Host "`n[1/3] Synthesizing CloudFormation templates..." -ForegroundColor Green
Set-Location -Path "$PSScriptRoot\..\infra"

.\node_modules\.bin\cdk.cmd synth --quiet

Write-Host "`n[2/3] Bootstrapping AWS CDK Environment in $Region..." -ForegroundColor Green
.\node_modules\.bin\cdk.cmd bootstrap "aws://$env:AWS_ACCOUNT_ID/$Region" --quiet

Write-Host "`n[3/3] Deploying OmniSettlement Production Stack to AWS..." -ForegroundColor Green
.\node_modules\.bin\cdk.cmd deploy --require-approval never

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host "  DEPLOYMENT COMPLETE! ALL PRIMITIVES LIVE ON AWS        " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
