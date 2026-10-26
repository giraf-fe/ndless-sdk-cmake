# ==============================================================================
# Native Windows Build, Install, and Test Launcher (build_windows.ps1)
# ==============================================================================
# Builds and installs the Ndless SDK locally on Windows, compiles the upstream
# samples, and optionally runs the unit and integration test suites.
#
# All writable state (Python venv, pip activity, temporary files, upstream
# checkout, build trees, and SDK installs) stays strictly inside this checkout.
# ==============================================================================

[CmdletBinding()]
param(
    [ValidateSet("Release", "Debug")]
    [string]$Configuration = "Release",
    [string]$ToolchainRoot = "",
    [string]$UpstreamDir = "",
    [string]$PythonExecutable = "",
    [ValidateRange(1, 256)]
    [int]$Jobs = 8,
    [switch]$Test
)

# ------------------------------------------------------------------------------
# Step 1: Verify native Windows host and define checked command runner
# ------------------------------------------------------------------------------
$ErrorActionPreference = "Stop"
$Root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "This launcher requires native Windows; use the portable CMake presets on other hosts."
}

function Invoke-Checked {
    param(
        [string]$Executable,
        [string[]]$Arguments
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable exited with code $LASTEXITCODE"
    }
}

# ------------------------------------------------------------------------------
# Step 2: Snapshot process environment variables before sandboxing
# ------------------------------------------------------------------------------
$EnvironmentNames = @(
    "TEMP",
    "TMP",
    "TMPDIR",
    "PYTHONDONTWRITEBYTECODE",
    "PIP_NO_CACHE_DIR",
    "PIP_DISABLE_PIP_VERSION_CHECK"
)
$SavedEnvironment = @{}
foreach ($Name in $EnvironmentNames) {
    $SavedEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
}

Push-Location $Root
try {
    # --------------------------------------------------------------------------
    # Step 3: Confine temporary files and pip flags to the local build tree
    # --------------------------------------------------------------------------
    $Temporary = Join-Path $Root "build/windows-temp"
    New-Item -ItemType Directory -Force -Path $Temporary | Out-Null

    foreach ($Name in @("TEMP", "TMP", "TMPDIR")) {
        [Environment]::SetEnvironmentVariable($Name, $Temporary, "Process")
    }
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PIP_NO_CACHE_DIR = "1"
    $env:PIP_DISABLE_PIP_VERSION_CHECK = "1"

    # --------------------------------------------------------------------------
    # Step 4: Prepare project-local Python venv and install requirements.txt
    # --------------------------------------------------------------------------
    # Note: This launcher creates a self-contained `.venv` in the repository root
    # (using -PythonExecutable or a native python.exe from PATH, which may be a
    # standard Python install or a Conda environment's python.exe). When running
    # CMake directly without this launcher, either a Python `venv` or a `conda`
    # environment with `pyelftools` can be used directly via -DPython3_EXECUTABLE.
    $Python = Join-Path $Root ".venv/Scripts/python.exe"
    if (-not (Test-Path -LiteralPath $Python)) {
        if ($PythonExecutable) {
            $HostPython = (Resolve-Path -LiteralPath $PythonExecutable).Path
        } else {
            $Command = Get-Command python.exe -ErrorAction SilentlyContinue
            if (-not $Command -or $Command.Source -like "*\WindowsApps\*") {
                throw "Supply -PythonExecutable with an existing native Python path; this launcher does not install system Python."
            }
            $HostPython = $Command.Source
        }
        Invoke-Checked -Executable $HostPython -Arguments @("-m", "venv", (Join-Path $Root ".venv"))
    }

    Invoke-Checked -Executable $Python -Arguments @(
        "-m", "pip",
        "--isolated",
        "--disable-pip-version-check",
        "install",
        "--no-cache-dir",
        "-r", "requirements.txt"
    )

    # --------------------------------------------------------------------------
    # Step 5: Locate or fetch the pinned upstream Ndless checkout
    # --------------------------------------------------------------------------
    if (-not $UpstreamDir) {
        $UpstreamDir = Join-Path $Root "upstream/Ndless"
    } else {
        $UpstreamDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($UpstreamDir)
    }

    if (-not (Test-Path -LiteralPath $UpstreamDir)) {
        Invoke-Checked -Executable $Python -Arguments @(
            "scripts/fetch_upstream.py",
            "--destination", $UpstreamDir
        )
    }

    # --------------------------------------------------------------------------
    # Step 6: Configure, build, and install the Ndless SDK
    # --------------------------------------------------------------------------
    $ToolArguments = @()
    if ($ToolchainRoot) {
        $ToolchainRoot = (Resolve-Path -LiteralPath $ToolchainRoot).Path
        $ToolArguments += "-DNDLESS_TOOLCHAIN_ROOT=$ToolchainRoot"
    }

    $Preset = "windows-" + $Configuration.ToLowerInvariant()
    $Prefix = Join-Path $Root "install/$Preset"

    Invoke-Checked -Executable cmake -Arguments (@(
        "--preset", $Preset,
        "-DCMAKE_INSTALL_PREFIX=$Prefix",
        "-DPython3_EXECUTABLE=$Python",
        "-DNDLESS_SOURCE_DIR=$UpstreamDir"
    ) + $ToolArguments)

    Invoke-Checked -Executable cmake -Arguments @(
        "--build",
        "--preset", $Preset,
        "--parallel", "$Jobs"
    )
    Invoke-Checked -Executable cmake -Arguments @(
        "--install",
        "build/$Preset"
    )

    # --------------------------------------------------------------------------
    # Step 7: Configure and build the upstream sample applications
    # --------------------------------------------------------------------------
    $Samples = "build/windows-samples-" + $Configuration.ToLowerInvariant()

    Invoke-Checked -Executable cmake -Arguments (@(
        "-S", "samples",
        "-B", $Samples,
        "-G", "Ninja",
        "-DCMAKE_BUILD_TYPE=$Configuration",
        "-DCMAKE_PREFIX_PATH=$Prefix",
        "-DCMAKE_TOOLCHAIN_FILE=$Prefix/share/ndless/cmake/TI-Nspire-Toolchain.cmake",
        "-DPython3_EXECUTABLE=$Python",
        "-DNDLESS_SOURCE_DIR=$UpstreamDir",
        "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF",
        "-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF"
    ) + $ToolArguments)

    Invoke-Checked -Executable cmake -Arguments @(
        "--build", $Samples,
        "--parallel", "$Jobs"
    )

    # --------------------------------------------------------------------------
    # Step 8: Run unit tests and full integration suite (when -Test is passed)
    # --------------------------------------------------------------------------
    if ($Test) {
        Invoke-Checked -Executable $Python -Arguments @(
            "-m", "unittest", "discover",
            "-s", "tests",
            "-p", "test_*.py",
            "-v"
        )

        $RunId = [Guid]::NewGuid().ToString("N")
        $Run = Join-Path $Root ("build/windows-tests-" + $Configuration.ToLowerInvariant() + "-" + $RunId)
        $TestArguments = @(
            "tests/integration.py",
            "--upstream", $UpstreamDir,
            "--work-dir", $Run,
            "--config", $Configuration
        )
        if ($ToolchainRoot) {
            $TestArguments += @("--toolchain-root", $ToolchainRoot)
        }
        Invoke-Checked -Executable $Python -Arguments $TestArguments
    }

    Write-Host "SDK installed locally: $Prefix"
    Write-Host "Samples: $(Join-Path $Root $Samples)"
} finally {
    # --------------------------------------------------------------------------
    # Step 9: Restore original process environment variables and working dir
    # --------------------------------------------------------------------------
    foreach ($Name in $EnvironmentNames) {
        [Environment]::SetEnvironmentVariable($Name, $SavedEnvironment[$Name], "Process")
    }
    Pop-Location
}
