param(
  [switch]$ApproveMcp,
  [switch]$KeepServer
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$baseUrl = "http://127.0.0.1:4173"
$resultPath = Join-Path $root "artifacts/mcp-observed-result.json"
$eventsPath = Join-Path $root "artifacts/mcp-observed-events.jsonl"
$codexStderrPath = Join-Path $root "artifacts/mcp-smoke-codex.err.log"
$promptPath = Join-Path $root "artifacts/mcp-smoke-prompt.txt"
$serverStdout = Join-Path $root "artifacts/mcp-smoke-server.out.log"
$serverStderr = Join-Path $root "artifacts/mcp-smoke-server.err.log"
$serverProcess = $null

if (-not $ApproveMcp) {
  Write-Error "MCP tool calls require explicit approval. Use -ApproveMcp only in an isolated test environment."
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $resultPath) | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $root "artifacts/playwright-mcp") | Out-Null

function Test-DemoServer {
  try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl/health" -TimeoutSec 2
    return $response.StatusCode -eq 200
  } catch {
    return $false
  }
}

try {
  if (-not (Test-DemoServer)) {
    $python = (Get-Command py -ErrorAction Stop).Source
    $serverProcess = Start-Process `
      -FilePath $python `
      -ArgumentList @("-X", "utf8", "examples/login_app/server.py") `
      -WorkingDirectory $root `
      -WindowStyle Hidden `
      -RedirectStandardOutput $serverStdout `
      -RedirectStandardError $serverStderr `
      -PassThru

    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
      Start-Sleep -Milliseconds 200
      if (Test-DemoServer) {
        $ready = $true
        break
      }
    }
    if (-not $ready) {
      throw "Demo server did not become ready at $baseUrl"
    }
  }

  $mcpArgs = @(
    "-y",
    "@playwright/mcp@0.0.84",
    "--headless",
    "--isolated",
    "--block-service-workers",
    "--redact-url-params",
    "access_token,code,state",
    "--output-dir",
    "./artifacts/playwright-mcp",
    "--allowed-origins",
    $baseUrl
  )
  $quotedMcpArgs = $mcpArgs | ForEach-Object {
    "'" + $_.Replace("'", "''") + "'"
  }
  $mcpArgToml = $quotedMcpArgs -join ", "
  $mcpConfig = "mcp_servers.playwright={ command='npx', args=[$mcpArgToml] }"

  $prompt = @"
Use only Playwright MCP. Call browser_navigate to open $baseUrl/login, then call browser_snapshot.
Base the output on the actual tool results and include every field required by the output schema.
Set mode to explore and authoritativeStatus to null. On success, error must be null.
Record separate browser_navigate and browser_snapshot steps with id, status, durationMs, intent, action, locatorUsed, and error.
Copy the Snapshot file path returned by browser_navigate verbatim into evidence.snapshot. Never use inline-snapshot.
Use null for evidence the tools did not produce.
Verify the username textbox, password textbox, and login button as three observed assertions. Include id, type, status, actual, durationMs, and error for each assertion.
Use these exact version values: Codex 0.166.0-alpha.5.1; Playwright MCP 0.0.84; ui-test-orchestrator@0.1.0.
Do not modify files and do not run shell commands.
"@
  Set-Content -LiteralPath $promptPath -Value $prompt -Encoding UTF8

  $codexArgs = @(
    "exec",
    "--skip-git-repo-check",
    "--ephemeral",
    "--approve-for-me",
    "-C",
    $root,
    "-c",
    $mcpConfig,
    "--output-schema",
    (Join-Path $root "schemas/codex-run-result.schema.json"),
    "--json",
    "-o",
    $resultPath
  )

  $savedErrorActionPreference = $ErrorActionPreference
  $codexExitCode = 1
  try {
    $ErrorActionPreference = "Continue"
    Get-Content -LiteralPath $promptPath -Raw |
      & codex @codexArgs 2> $codexStderrPath |
      Tee-Object -FilePath $eventsPath
    $codexExitCode = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $savedErrorActionPreference
  }
  if ($codexExitCode -ne 0) {
    throw "codex exec exited with code $codexExitCode; see $codexStderrPath"
  }

  & py -X utf8 (Join-Path $root "scripts/validate_codex_result.py") $resultPath --require-snapshot
  if ($LASTEXITCODE -ne 0) {
    throw "MCP result failed schema or snapshot evidence validation"
  }
} finally {
  if ($null -ne $serverProcess -and -not $KeepServer) {
    Stop-Process -Id $serverProcess.Id -ErrorAction SilentlyContinue
  }
}
