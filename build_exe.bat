@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "WORKSPACE_DIR=%CD%"
set "PORTABLE_DIR=%WORKSPACE_DIR%\.portable"
set "BUILD_VENV=%WORKSPACE_DIR%\.venv"
set "PIP_CACHE_DIR=%PORTABLE_DIR%\pip-cache"
set "BUILD_DIR=%PORTABLE_DIR%\pyinstaller-build"
set "SPEC_DIR=%PORTABLE_DIR%\pyinstaller-spec"
set "APP_NAME=Damn Simple ComfyUI Manager"
set "EXE_NAME=DS-ComfyUI-Manager"
set "EXE_PATH=%WORKSPACE_DIR%\release\%EXE_NAME%.exe"
set "DIST_DIR=%WORKSPACE_DIR%\release"
set "ICON_PATH=%WORKSPACE_DIR%\assets\DSCUIM.ico"
set "SEVEN_ZIP_PATH=%WORKSPACE_DIR%\assets\7zr.exe"
set "SEVEN_ZIP_URL=https://github.com/ip7z/7zip/releases/download/26.01/7zr.exe"
set "HELPER_PROJECT=%WORKSPACE_DIR%\browser\DS-ComfyUI-Browser.csproj"
set "BROWSER_DIR=%WORKSPACE_DIR%\browser"
set "BROWSER_PUBLISH_DIR=%PORTABLE_DIR%\browser-publish"
set "BROWSER_EXE=%BROWSER_PUBLISH_DIR%\DS-ComfyUI-Browser.exe"
set "UV_DIR=%PORTABLE_DIR%\uv"
set "UV_EXE=%UV_DIR%\uv.exe"
set "UV_CACHE_DIR=%PORTABLE_DIR%\uv-cache"
set "UV_PYTHON_INSTALL_DIR=%PORTABLE_DIR%\python"
set "PYTHONPYCACHEPREFIX=%PORTABLE_DIR%\pycache"
set "PYINSTALLER_CONFIG_DIR=%PORTABLE_DIR%\pyinstaller-config"
set "TEMP=%PORTABLE_DIR%\temp"
set "TMP=%PORTABLE_DIR%\temp"
set "LOG_FILE=%PORTABLE_DIR%\build.log"
set "PYTHONNOUSERSITE=1"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "PIP_REQUIRE_VIRTUALENV=1"

if not exist "%PORTABLE_DIR%" mkdir "%PORTABLE_DIR%"
if not exist "%PIP_CACHE_DIR%" mkdir "%PIP_CACHE_DIR%"
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"
if not exist "%UV_DIR%" mkdir "%UV_DIR%"
if not exist "%TEMP%" mkdir "%TEMP%"

echo ============================================================
echo  Portable build - %APP_NAME%
echo ============================================================
echo Workspace: %WORKSPACE_DIR%
echo Venv:      %BUILD_VENV%
echo Python:    %UV_PYTHON_INSTALL_DIR%
echo Output:    %EXE_PATH%
echo Log:       %LOG_FILE%
echo.
echo Build started > "%LOG_FILE%"

if not exist "app.py" goto missing_app
if not exist "requirements.txt" goto missing_requirements
if not exist "%ICON_PATH%" goto missing_icon
if not exist "%WORKSPACE_DIR%\assets" mkdir "%WORKSPACE_DIR%\assets"

echo [setup] Building dedicated WebView2 browser helper
if not exist "%HELPER_PROJECT%" goto missing_browser_project
where dotnet >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto missing_dotnet
if exist "%BROWSER_PUBLISH_DIR%" powershell -NoProfile -ExecutionPolicy Bypass -Command "Remove-Item -LiteralPath '%BROWSER_PUBLISH_DIR%' -Recurse -Force" >> "%LOG_FILE%" 2>&1
if not exist "%BROWSER_PUBLISH_DIR%" mkdir "%BROWSER_PUBLISH_DIR%"
dotnet publish "%HELPER_PROJECT%" ^
    -c Release ^
    -r win-x64 ^
    --self-contained false ^
    -p:PublishSingleFile=true ^
    -p:IncludeNativeLibrariesForSelfExtract=true ^
    -p:DebugType=None ^
    -p:DebugSymbols=false ^
    -o "%BROWSER_PUBLISH_DIR%" >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto fail_browser_helper
copy /Y "%ICON_PATH%" "%BROWSER_PUBLISH_DIR%\DSCUIM.ico" >> "%LOG_FILE%" 2>&1
if not exist "%BROWSER_EXE%" goto fail_browser_helper_missing

echo [setup] Checking portable 7-Zip extractor
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $path='%SEVEN_ZIP_PATH%'; $url='%SEVEN_ZIP_URL%'; function Test-Exe($p) { if (-not (Test-Path -LiteralPath $p)) { return $false }; $bytes=[System.IO.File]::ReadAllBytes($p); if ($bytes.Length -lt 102400) { return $false }; return ($bytes[0] -eq 0x4D -and $bytes[1] -eq 0x5A) }; if (-not (Test-Exe $path)) { if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }; Invoke-WebRequest -Uri $url -OutFile $path; if (-not (Test-Exe $path)) { throw 'Downloaded 7zr.exe is not a valid Windows executable' } }" >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto fail_7zr

if not exist "%UV_EXE%" (
    echo [setup] Downloading portable uv into %UV_DIR%
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $zip=Join-Path '%PORTABLE_DIR%' 'uv.zip'; Invoke-WebRequest -Uri 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile $zip; Expand-Archive -Path $zip -DestinationPath '%PORTABLE_DIR%\uv_extract' -Force; $exe=Get-ChildItem '%PORTABLE_DIR%\uv_extract' -Recurse -Filter uv.exe | Select-Object -First 1; if (-not $exe) { throw 'uv.exe was not found in the downloaded zip' }; Copy-Item $exe.FullName '%UV_EXE%' -Force; Remove-Item $zip -Force; Remove-Item '%PORTABLE_DIR%\uv_extract' -Recurse -Force" >> "%LOG_FILE%" 2>&1
    if errorlevel 1 goto fail_uv
)

if not exist "%BUILD_VENV%\Scripts\python.exe" (
    echo [setup] Installing local Python in the workspace
    "%UV_EXE%" python install 3.12 >> "%LOG_FILE%" 2>&1
    if errorlevel 1 goto fail_python

    echo [setup] Creating local .venv
    "%UV_EXE%" venv --python 3.12 "%BUILD_VENV%" >> "%LOG_FILE%" 2>&1
    if errorlevel 1 goto fail_venv
)

echo [setup] Checking pip in .venv
"%BUILD_VENV%\Scripts\python.exe" -m ensurepip --upgrade >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto fail_ensurepip

echo [setup] Updating pip in .venv
"%BUILD_VENV%\Scripts\python.exe" -m pip install --upgrade pip --cache-dir "%PIP_CACHE_DIR%" >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto fail_pip

echo [setup] Installing dependencies and PyInstaller in .venv
"%BUILD_VENV%\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller==6.11.1 --cache-dir "%PIP_CACHE_DIR%" >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto fail_deps

echo [build] Generating single-file portable EXE
"%BUILD_VENV%\Scripts\python.exe" -m PyInstaller app.py ^
    --name "%EXE_NAME%" ^
    --noconsole ^
    --onefile ^
    --clean ^
    --runtime-tmpdir "%WORKSPACE_DIR%\_temp" ^
    --icon "%ICON_PATH%" ^
    --add-data "%ICON_PATH%;assets" ^
    --add-data "%SEVEN_ZIP_PATH%;assets" ^
    --add-data "%BROWSER_PUBLISH_DIR%;browser" ^
    --distpath "%DIST_DIR%" ^
    --workpath "%BUILD_DIR%" ^
    --specpath "%SPEC_DIR%" >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto fail_build

if not exist "%EXE_PATH%" goto fail_missing_exe

echo.
echo [ok] Portable EXE created:
echo %EXE_PATH%
echo.
echo The dedicated browser helper is embedded in the EXE and will be
echo extracted into the local browser folder when the app starts.
echo.
echo All build files stay inside the workspace:
echo - .venv
echo - .portable
echo - release
echo.
echo Press any key to close...
powershell -NoProfile -Command "$Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown') | Out-Null"
exit /b 0

:missing_app
echo [error] app.py is missing.
goto fail_common

:missing_requirements
echo [error] requirements.txt is missing.
goto fail_common

:missing_icon
echo [error] assets\DSCUIM.ico is missing.
goto fail_common

:missing_browser_project
echo [error] browser\DS-ComfyUI-Browser.csproj is missing.
goto fail_common

:missing_dotnet
echo [error] .NET SDK is not available in PATH.
goto fail_common

:fail_7zr
echo [error] Portable 7-Zip extractor download or validation failed.
goto fail_common

:fail_uv
echo [error] uv download or setup failed.
goto fail_common

:fail_python
echo [error] Local Python installation failed.
goto fail_common

:fail_venv
echo [error] Local .venv creation failed.
goto fail_common

:fail_ensurepip
echo [error] pip setup inside .venv failed.
goto fail_common

:fail_pip
echo [error] pip update failed.
goto fail_common

:fail_deps
echo [error] Dependency installation failed.
goto fail_common

:fail_browser_helper
echo [error] Dedicated browser helper build failed.
goto fail_common

:fail_browser_helper_missing
echo [error] Dedicated browser helper executable was not found after build.
goto fail_common

:fail_build
echo [error] PyInstaller could not generate the executable.
goto fail_common

:fail_missing_exe
echo [error] Build finished but the EXE was not found at:
echo %EXE_PATH%
goto fail_common

:fail_common
echo.
echo This batch stays open so you can read the error.
echo Full log:
echo %LOG_FILE%
echo.
echo Press any key to close...
powershell -NoProfile -Command "$Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown') | Out-Null"
exit /b 1
