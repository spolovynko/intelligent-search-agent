param(
    [switch]$Build
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. Add OPENAI_API_KEY before ingestion or LLM calls."
}

if ($Build) {
    docker compose --env-file .env up --build -d
} else {
    docker compose --env-file .env up -d
}

Write-Host ""
Write-Host "Assistant UI: http://localhost:8000/"
Write-Host "API docs:     http://localhost:8000/docs"
Write-Host "Health:       http://localhost:8000/health"
Write-Host "pgAdmin DB:   127.0.0.1:5433 / intelligent_search_agent / postgres / postgres"
