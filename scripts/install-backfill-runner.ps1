<#
.SYNOPSIS
Install the native, operator-owned backfill supervisor at Windows sign-in.
.DESCRIPTION
Check and Print are read-only preflight/plan operations. Install replaces the
same task after cooperative drain; Stop disables it and drains; Uninstall also
removes it. Status reports task/host state, not the Redis runner heartbeat.
No container action is performed. Environment values never enter task XML.
#>
[CmdletBinding()]
param(
    [ValidateSet('Install', 'Check', 'Print', 'Status', 'Stop', 'Uninstall')]
    [string]$Mode = 'Install',
    [string]$RepoRoot,
    [string]$EnvFile,
    [string]$Python,
    [ValidatePattern('^[A-Za-z0-9._-]+$')]
    [string]$TaskName = 'Imoveis-Backfill-Supervisor'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-HostCommand([string]$HostMode) {
    & $Python $HostScript $HostMode --repo-root $RepoRoot --env-file $EnvFile
    if ($LASTEXITCODE -ne 0) {
        throw 'Backfill host command failed. No process was forcibly terminated.'
    }
}

function Quote-NativeArgument([string]$Value) {
    if ($Value.Contains('"')) { throw 'A command argument contains an unsupported quote.' }
    # CommandLineToArgvW requires doubling trailing backslashes before a quote.
    return '"' + ($Value -replace '(\\+)$', '$1$1') + '"'
}

function Stop-RegisteredHost($Task) {
    if ($null -ne $Task) {
        Disable-ScheduledTask -TaskName $TaskName | Out-Null
        # A reinstall after moving the checkout must drain the OLD action's
        # working directory before registering anything against the new path.
        $previousRoot = [string]$Task.Actions[0].WorkingDirectory
        if ($previousRoot -and $previousRoot -ne $RepoRoot) {
            & $Python $HostScript stop --repo-root $previousRoot
            if ($LASTEXITCODE -ne 0) { throw 'The previous host did not drain.' }
        }
    }
    Invoke-HostCommand 'stop'
}

try {
    if ([Environment]::OSVersion.Platform -ne 'Win32NT') {
        throw 'This installer requires native Windows PowerShell.'
    }
    if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
    $RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
    if (-not $EnvFile) { $EnvFile = Join-Path $RepoRoot '.env.local' }
    $EnvFile = [IO.Path]::GetFullPath($EnvFile)
    if (-not $Python) { $Python = Join-Path $RepoRoot '.venv\Scripts\python.exe' }
    $Python = (Resolve-Path -LiteralPath $Python).Path
    $HostScript = Join-Path $RepoRoot 'scripts\windows\backfill_host.py'
    if (-not (Test-Path -LiteralPath $HostScript -PathType Leaf)) {
        throw 'The native backfill host script is missing.'
    }
    & $Python -c 'import sys; raise SystemExit(0 if sys.platform == ''win32'' else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'The selected Python must run natively on Windows.' }

    if ($Mode -eq 'Check') {
        Invoke-HostCommand 'check'
        return
    }

    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -ne $existing -and (
        -not $existing.Description.StartsWith('Imoveis host-side backfill;') -or
        @($existing.Actions).Count -ne 1 -or
        -not $existing.Actions[0].Arguments.Contains('backfill_host.py')
    )) {
        throw 'The task name is already owned by a different application.'
    }
    if ($Mode -eq 'Status') {
        if ($null -eq $existing) {
            Write-Output 'Task is not installed.'
            & $Python $HostScript status --repo-root $RepoRoot
            exit 1
        }
        Write-Output ('Task: {0}; state: {1}' -f $TaskName, $existing.State)
        & $Python $HostScript status --repo-root $RepoRoot
        exit $LASTEXITCODE
    }

    if ($Mode -eq 'Stop' -or $Mode -eq 'Uninstall') {
        Stop-RegisteredHost $existing
        if ($Mode -eq 'Uninstall' -and $null -ne $existing) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Output 'Backfill task uninstalled.'
        }
        return
    }

    $Pythonw = Join-Path (Split-Path -Parent $Python) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $Pythonw -PathType Leaf)) {
        throw 'The matching pythonw.exe is missing; rebuild the native virtual environment.'
    }
    $User = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $Arguments = @('-u', (Quote-NativeArgument $HostScript), 'run', '--repo-root',
        (Quote-NativeArgument $RepoRoot), '--env-file', (Quote-NativeArgument $EnvFile)) -join ' '
    $action = New-ScheduledTaskAction -Execute $Pythonw -Argument $Arguments -WorkingDirectory $RepoRoot
    $signin = New-ScheduledTaskTrigger -AtLogOn -User $User
    $signin.Delay = 'PT15S'
    # A repeating recovery trigger also covers exhausted restart counters after
    # a prolonged broken environment. IgnoreNew keeps a healthy process alone.
    $recovery = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -DisallowHardTerminate `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -Hidden
    $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
    $definition = New-ScheduledTask -Action $action -Trigger @($signin, $recovery) -Settings $settings -Principal $principal `
        -Description 'Imoveis host-side backfill; starts at user sign-in, private env, cooperative stop.'

    if ($Mode -eq 'Print') {
        [ordered]@{
            task_name = $TaskName
            execute = $action.Execute
            arguments = $action.Arguments
            working_directory = $action.WorkingDirectory
            user = $User
            logon_type = [string]$principal.LogonType
            multiple_instances = [string]$settings.MultipleInstances
            execution_time_limit = $settings.ExecutionTimeLimit
            allow_hard_terminate = $settings.AllowHardTerminate
            stop_on_battery = $settings.StopIfGoingOnBatteries
            disallow_start_on_battery = $settings.DisallowStartIfOnBatteries
        } | ConvertTo-Json
        return
    }

    Invoke-HostCommand 'check'
    # Also drains a manually launched wrapper that owns this checkout's lock.
    Stop-RegisteredHost $existing
    Register-ScheduledTask -TaskName $TaskName -InputObject $definition -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    Write-Output ('Installed {0}. It runs without a console under {1} after sign-in.' -f $TaskName, $User)
    Write-Output 'Check -Mode Status and .run\backfill-host\host.log; Redis runner_present is separate runtime evidence.'
}
catch {
    # Native configuration errors may include original input. Our Python
    # preflight prints only vetted setting names; do not dump exception objects.
    Write-Error 'Backfill task operation failed. Check the native interpreter, checkout paths, task permissions and host log.'
    exit 1
}
