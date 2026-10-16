# 打包“快捷翻译”为单文件 exe（Windows PowerShell）
# 用法：  & "$PSScriptRoot\build_exe.ps1"
# 脚本位于 <项目根>/scripts/，下面按脚本自身位置自动定位项目根，
# 因此整个项目拷贝到任意目录 / 任意电脑都能直接打包，无需改路径。
$ErrorActionPreference = "Stop"

$root = Split-Path $PSScriptRoot -Parent
$src  = Join-Path $root "src"
$pkg  = Join-Path $root "build_pkg"
$out  = Join-Path $root "快捷翻译.exe"

# 优先使用项目内虚拟环境的 PyInstaller，找不到则回退到 PATH 中的 pyinstaller
$pyi = Join-Path $root ".build_env\Scripts\pyinstaller.exe"
if (-not (Test-Path $pyi)) { $pyi = "pyinstaller" }

New-Item -ItemType Directory -Force $pkg | Out-Null
Remove-Item Env:PIP_CONFIG_FILE -ErrorAction SilentlyContinue

& $pyi `
  --onefile --windowed --name "快捷翻译" `
  --icon (Join-Path $src "app.ico") `
  --add-data "$(Join-Path $src 'app.ico');." `
  --collect-all winocr --collect-all winrt `
  --distpath (Join-Path $pkg "dist") `
  --workpath (Join-Path $pkg "build") `
  --specpath $pkg `
  --noconfirm (Join-Path $src "fanyi.py")

Copy-Item (Join-Path $pkg "dist\快捷翻译.exe") $out -Force
Write-Output "BUILD DONE"
Get-Item $out | Select-Object FullName, Length
