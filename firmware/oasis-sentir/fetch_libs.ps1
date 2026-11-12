# Baixa as bibliotecas Arduino do Monitor Oasis (versoes fixas) para .\libraries
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force libraries | Out-Null
Set-Location libraries
$libs = @(
  @("sparkfun/SparkFun_MAX3010x_Sensor_Library","SparkFun_MAX3010x_Sensor_Library","v1.1.2"),
  @("adafruit/Adafruit-MLX90614-Library","Adafruit-MLX90614-Library","2.1.7"),
  @("adafruit/Adafruit_AHTX0","Adafruit_AHTX0","2.0.6"),
  @("adafruit/Adafruit_BMP280_Library","Adafruit_BMP280_Library","3.0.0"),
  @("adafruit/Adafruit_BusIO","Adafruit_BusIO","1.17.4"),
  @("adafruit/Adafruit_Sensor","Adafruit_Sensor","1.1.15")
)
foreach ($l in $libs) { if (-not (Test-Path $l[1])) { git -c advice.detachedHead=false clone -q --depth 1 --branch $l[2] "https://github.com/$($l[0]).git" $l[1] } }
Write-Host "Bibliotecas em $(Get-Location)"
