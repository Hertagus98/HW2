param(
  [string]$OutputPath = "monitor.csv",
  [int]$DurationSeconds = 40,
  [int]$IntervalSeconds = 2
)

$ErrorActionPreference = 'SilentlyContinue'
"timestamp_utc,status_code,latency_ms,service_version" | Set-Content -Path $OutputPath -Encoding utf8
$deadline = (Get-Date).ToUniversalTime().AddSeconds($DurationSeconds)
while ((Get-Date).ToUniversalTime() -lt $deadline) {
  $started = Get-Date
  $status = 0
  $version = ''
  try {
    $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/version' -UseBasicParsing -TimeoutSec 5
    $status = [int]$response.StatusCode
    $version = (($response.Content | ConvertFrom-Json).version)
  } catch { $status = 0 }
  $latency = [math]::Round(((Get-Date) - $started).TotalMilliseconds, 2)
  "{0},{1},{2},{3}" -f (Get-Date).ToUniversalTime().ToString('o'), $status, $latency, $version | Add-Content -Path $OutputPath -Encoding utf8
  Start-Sleep -Seconds $IntervalSeconds
}
