# push_images.ps1 — Build and push both Docker images to ECR
# Run from GasModel root:  .\scripts\push_images.ps1 -Region eu-west-2 -Env dev

param(
    [string]$Region  = "eu-west-2",
    [string]$Env     = "dev",
    [string]$Tag     = "latest"
)

$Account = (aws sts get-caller-identity --query Account --output text)
$EcrBase = "$Account.dkr.ecr.$Region.amazonaws.com"

Write-Host "Logging in to ECR..."
aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin $EcrBase

# ── gas-model ─────────────────────────────────────────────────────────────────
Write-Host "Building gas-model..."
docker build -t gas-model "$PSScriptRoot\.."

docker tag  "gas-model:latest" "$EcrBase/gas-model:$Tag"
docker push "$EcrBase/gas-model:$Tag"
Write-Host "Pushed gas-model:$Tag"

# ── gas-scraper ───────────────────────────────────────────────────────────────
Write-Host "Building gas-scraper..."
docker build -t gas-scraper "$PSScriptRoot\..\..\..\Scrapes\gas"

docker tag  "gas-scraper:latest" "$EcrBase/gas-scraper:$Tag"
docker push "$EcrBase/gas-scraper:$Tag"
Write-Host "Pushed gas-scraper:$Tag"

Write-Host "Done. Update ECS services to pick up new images:"
Write-Host "  aws ecs update-service --cluster gasmodel-$Env-cluster --service gasmodel-$Env-listener --force-new-deployment --region $Region"
Write-Host "  aws ecs update-service --cluster gasmodel-$Env-cluster --service gasmodel-$Env-dashboard --force-new-deployment --region $Region"
