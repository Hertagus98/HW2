param(
  [string]$OutputPath = "monitor.csv",
  [string]$StopPath = "",
  [int]$DurationSeconds = 40,
  [int]$IntervalSeconds = 2
)

$ErrorActionPreference = 'Stop'
$deadline = (Get-Date).ToUniversalTime().AddSeconds($DurationSeconds)
while ((Get-Date).ToUniversalTime() -lt $deadline) {
  if ($StopPath -and (Test-Path -LiteralPath $StopPath)) { break }
  $timer = [System.Diagnostics.Stopwatch]::StartNew()
  $status = 0
  $version = ''
  try {
    $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/version' -UseBasicParsing -TimeoutSec 5
    $status = [int]$response.StatusCode
    $version = (($response.Content | ConvertFrom-Json).version)
  } catch {
    if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
  }
  $timer.Stop()
  [pscustomobject]@{
    timestamp_utc = (Get-Date).ToUniversalTime().ToString('o')
    status_code = $status
    latency_ms = $timer.Elapsed.TotalMilliseconds.ToString('F2', [cultureinfo]::InvariantCulture)
    service_version = $version
  } | Export-Csv -LiteralPath $OutputPath -Append -NoTypeInformation -Encoding UTF8
  Start-Sleep -Seconds $IntervalSeconds
}
