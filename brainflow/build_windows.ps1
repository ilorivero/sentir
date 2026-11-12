# SENTIR - compila o BrainFlow com o driver MeowerBoard no Windows e instala o pacote Python.
# Requisitos: Git, Python 3.10+, CMake >= 3.21, Visual Studio 2022 (Desktop C++).
# Uso (PowerShell, na pasta SENTIR\brainflow):   .\build_windows.ps1
param(
    [string]$BrainflowDir = "$PSScriptRoot\..\_deps\brainflow",
    [string]$Ref = "master"
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path $BrainflowDir)) {
    git clone https://github.com/brainflow-dev/brainflow.git $BrainflowDir
}
Push-Location $BrainflowDir
git fetch origin
git checkout $Ref
Pop-Location

python "$PSScriptRoot\integrate_meower.py" $BrainflowDir

Push-Location $BrainflowDir
# build.py escolhe o gerador do Visual Studio e copia as DLLs para os pacotes de linguagem
python tools\build.py --no-synchroni --no-tests --num-jobs 8
python -m pip install --upgrade .\python_package
Pop-Location

python -c "from brainflow.board_shim import BoardIds; print('MEOWER_BOARD =', int(BoardIds.MEOWER_BOARD))"
Write-Host "Teste com o simulador:  python $PSScriptRoot\test_driver_with_sim.py"
