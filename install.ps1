<#
.SYNOPSIS
Installs Pense-bete for the current user and adds it to the Start menu.

.DESCRIPTION
The Windows counterpart of install.sh.

  .\install.ps1 [-Target <dir>]    install (asks for the directory if not given)
  .\install.ps1 -Uninstall         remove the application, and on request its data
  -Purge                           with -Uninstall: delete the notes and settings too
  .\install.ps1 -Dev               register this clone as "Pense-bete (dev)"
  -Yes                             ask nothing, take the default answers
  -Commit <sha> -Release <tag>     what is installed, for a copy without git
  -Standalone                      install the standalone version, which carries
                                   Python: offered anyway when Python is missing
  -WaitPid <pid> -Launch           wait for that process to end before installing,
                                   then launch the application: for its own updates

Also runs on its own, without a clone of the repository; it then installs the newest
release, the highest vX.Y.Z tag:
  irm https://raw.githubusercontent.com/WatoLua/pense-bete/main/install.ps1 | iex
#>
[CmdletBinding()]
param(
    [string]$Target = "",
    [switch]$Uninstall,
    [switch]$Purge,
    [switch]$Dev,
    [switch]$Yes,
    [string]$Commit = "",
    [string]$Release = "",
    [switch]$Standalone,
    [int]$WaitPid = 0,
    [switch]$Launch,
    [switch]$RemoveSource
)

$ErrorActionPreference = "Stop"

# The development version runs from a clone and has its own Start menu entry and notes,
# apart from the installed application.
$AppId = if ($Dev) { "pense-bete-dev" } else { "pense-bete" }
$AppName = [regex]::Unescape($(if ($Dev) { "Pense-b\u00eate (dev)" } else { "Pense-b\u00eate" }))
$RepoUrl = if ($env:PENSE_BETE_REPO) { $env:PENSE_BETE_REPO } else { "https://github.com/WatoLua/pense-bete.git" }
# The application beside the script, as a clone, an archive or the standalone build;
# empty when the script runs through Invoke-Expression: the application is then
# downloaded.
$SourceDir = ""
if ($PSScriptRoot -and ((Test-Path -LiteralPath (Join-Path $PSScriptRoot "pense_bete.py")) -or
                        (Test-Path -LiteralPath (Join-Path $PSScriptRoot "Pense-bete.exe")))) {
    $SourceDir = $PSScriptRoot
}
$DefaultDir = Join-Path $env:LOCALAPPDATA "Programs\$AppId"
# PENSE_BETE_SHORTCUT_DIR stands in for the Start menu in the tests.
$ShortcutDir = if ($env:PENSE_BETE_SHORTCUT_DIR) { $env:PENSE_BETE_SHORTCUT_DIR } else { [Environment]::GetFolderPath("Programs") }
$Shortcut = Join-Path $ShortcutDir "$AppName.lnk"
# Where the application keeps its data, as pensebete/config.py computes it.
$AppData = Join-Path $env:APPDATA $AppId
$DataDir = if ($env:PENSE_BETE_DIR) { $env:PENSE_BETE_DIR } else { Join-Path $AppData "notes" }
$Files = "pense_bete.py", "icon.svg", "icon.ico", "requirements.txt", "install.ps1", "install.sh", "LICENSE"
$Package = "pensebete"
# The standalone version: an executable carrying Python and PySide6, built for every
# release and attached to it on GitHub.
$Executable = "Pense-bete.exe"
$BundleAsset = "pense-bete-windows.zip"
$Bundle = $false

# Messages are in French when Windows is, in English otherwise. This file is ASCII, so
# that Windows PowerShell reads it right with or without a byte order mark, which
# Invoke-Expression would choke on: accented letters are written \u00e9 and decoded here,
# and values come in through -f, after the decoding, so that no path is decoded.
$French = (Get-UICulture).TwoLetterISOLanguageName -eq "fr"
function T([string]$English, [string]$Francais, [object[]]$Values = @()) {
    $text = if ($French) { [regex]::Unescape($Francais) } else { $English }
    return $text -f $Values
}

function Info([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Warn([string]$Message) { Write-Host "/!\ $Message" -ForegroundColor Yellow }
# Thrown rather than exit: run through Invoke-Expression, exit would close the window.
function Fail([string]$Message) { throw "$(T 'Error:' 'Erreur :') $Message" }

# -Yes skips the questions, for the application's own update and uninstall; without a
# console to answer in, the default applies.
function Ask([string]$Prompt) {
    if ($Yes) { return "" }
    try { return Read-Host $Prompt } catch { return "" }
}
function AskYes([string]$Question) {  # default yes
    $answer = Ask "$Question $(T '[Y/n]' '[O/n]')"
    return (-not $answer) -or ($answer -match '^[yYoO]')
}
function AskNo([string]$Question) {  # default no
    return (Ask "$Question $(T '[y/N]' '[o/N]')") -match '^[yYoO]'
}

# A native command, its output returned and its exit code in $LASTEXITCODE. What it writes
# on stderr is dropped: with "Stop", Windows PowerShell would take it for an error.
function Native([string]$File, [string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { return & $File @Arguments 2>$null } finally { $ErrorActionPreference = $previous }
}

function Delete-Data {
    # Only what the application wrote: note directories, then the data directory if that
    # leaves it empty, so that a PENSE_BETE_DIR pointing elsewhere loses nothing else.
    if (Test-Path -LiteralPath $DataDir) {
        Get-ChildItem -LiteralPath $DataDir -Directory | Where-Object {
            Test-Path -LiteralPath (Join-Path $_.FullName "note.json")
        } | Remove-Item -Recurse -Force
        if (-not (Get-ChildItem -LiteralPath $DataDir -Force)) { Remove-Item -LiteralPath $DataDir }
    }
    foreach ($name in "session.json", "session.tmp") {
        Remove-Item -LiteralPath (Join-Path $AppData $name) -Force -ErrorAction SilentlyContinue
    }
    if ((Test-Path -LiteralPath $AppData) -and -not (Get-ChildItem -LiteralPath $AppData -Force)) {
        Remove-Item -LiteralPath $AppData
    }
}

function Do-Uninstall {
    $purgeData = [bool]$Purge
    # Asked first, so the answer does not depend on what the removal prints. Default no:
    # the notes cannot be recovered once deleted.
    if (-not $purgeData -and (Test-Path -LiteralPath $DataDir) -and
            (AskNo (T "Also delete the notes and settings ({0})? They cannot be recovered." "Supprimer aussi les post-its et les r\u00e9glages ({0}) ? Ils ne pourront pas \u00eatre r\u00e9cup\u00e9r\u00e9s." $DataDir))) {
        $purgeData = $true
    }
    # The shortcut records where the application was installed.
    $installDir = ""
    if (Test-Path -LiteralPath $Shortcut) {
        $link = (New-Object -ComObject WScript.Shell).CreateShortcut($Shortcut)
        if ($link.Arguments -match '"([^"]+)\\pense_bete\.py"') {
            $installDir = $Matches[1]
        } elseif ((Split-Path -Leaf $link.TargetPath) -eq $Executable) {
            $installDir = Split-Path $link.TargetPath
        }
    }
    # A git working copy is a clone the application was installed in place from: it is
    # the user's own checkout, so only the Start menu entry is removed.
    if ($installDir -and (Test-Path -LiteralPath (Join-Path $installDir ".git"))) {
        Warn (T "{0} is a git repository, it is kept." "{0} est un d\u00e9p\u00f4t git, il est conserv\u00e9." $installDir)
    } elseif ($installDir -and ((Test-Path -LiteralPath (Join-Path $installDir "pense_bete.py")) -or
                                (Test-Path -LiteralPath (Join-Path $installDir $Executable)))) {
        if (AskYes (T "Delete {0}?" "Supprimer {0} ?" $installDir)) {
            Remove-Item -LiteralPath $installDir -Recurse -Force
        }
    }
    Remove-Item -LiteralPath $Shortcut -Force -ErrorAction SilentlyContinue
    if ($purgeData) {
        Delete-Data
        Info (T "{0} is uninstalled, with its notes and settings." "{0} est d\u00e9sinstall\u00e9, avec ses post-its et ses r\u00e9glages." $AppName)
    } else {
        Info (T "{0} is uninstalled. Notes are kept in {1}." "{0} est d\u00e9sinstall\u00e9. Les post-its sont conserv\u00e9s dans {1}." @($AppName, $DataDir))
    }
}

function Find-Python {
    # The python on the PATH first, the one pip installs for; the Microsoft Store's
    # placeholder, when Python is not installed, fails to run and is passed over.
    foreach ($candidate in @(@("python"), @("python3"), @("py", "-3"))) {
        if (-not (Get-Command $candidate[0] -ErrorAction SilentlyContinue)) { continue }
        $arguments = @($candidate | Select-Object -Skip 1) + @("-c", "import sys; print(sys.executable)")
        $executable = Native $candidate[0] $arguments
        if ($LASTEXITCODE -eq 0 -and $executable -and (Test-Path -LiteralPath "$executable".Trim())) {
            return "$executable".Trim()
        }
    }
    return ""
}

function Latest-Release {  # the newest vX.Y.Z tag of $RepoUrl, "" when it has none
    $tags = Native "git" @("ls-remote", "--tags", "--refs", "--", $RepoUrl, "refs/tags/v*")
    $releases = @($tags | ForEach-Object { ($_ -split "refs/tags/")[-1] } |
        Where-Object { $_ -match '^v\d+\.\d+\.\d+$' } |
        Sort-Object { [version]$_.Substring(1) })
    if ($releases.Count) { return $releases[-1] }
    return ""
}

function GitHub-Api {  # the GitHub API address of $RepoUrl, "" for a repository elsewhere
    if ($env:PENSE_BETE_API) { return $env:PENSE_BETE_API.TrimEnd("/") }
    if ($RepoUrl -match '^https://github\.com/([^/]+)/([^/]+?)(\.git)?/?$') {
        return "https://api.github.com/repos/$($Matches[1])/$($Matches[2])"
    }
    return ""
}

# The newest release through the GitHub API: its tag, commit and archives.
function Newest-Tag([string]$Api) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $tags = @(Invoke-RestMethod -Uri "$Api/tags?per_page=100" -Headers @{ "User-Agent" = "pense-bete" } -UseBasicParsing |
        ForEach-Object { $_ } | Where-Object { $_.name -match '^v\d+\.\d+\.\d+$' } |
        Sort-Object { [version]$_.name.Substring(1) })
    if (-not $tags.Count) { throw "no release" }
    return $tags[-1]
}

# A download written to a file, its progress shown in megabytes on one line. Rather
# than Invoke-WebRequest, whose progress bar Windows PowerShell redraws for every block
# received, slowing a download of tens of megabytes down many times over.
function Save-Url([string]$Url, [string]$Path) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $request = [Net.HttpWebRequest]::Create($Url)
    $request.UserAgent = "pense-bete"
    $response = $request.GetResponse()
    $stream = $response.GetResponseStream()
    $file = [IO.File]::Create($Path)
    try {
        $unit = T "MB" "Mo"
        # GitHub's source archives are made on the fly, their size unknown beforehand.
        $total = if ($response.ContentLength -gt 0) { " / {0} {1}" -f [math]::Round($response.ContentLength / 1MB), $unit } else { " $unit" }
        $buffer = New-Object byte[] 262144
        $received = 0
        $shown = -1
        while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $file.Write($buffer, 0, $read)
            $received += $read
            $megabytes = [math]::Floor($received / 1MB)
            if ($megabytes -ne $shown) {  # once per megabyte, not per block
                $shown = $megabytes
                Write-Host -NoNewline "`r    $megabytes$total"
            }
        }
        Write-Host ""
    } finally {
        $file.Dispose()
        $stream.Dispose()
        $response.Dispose()
    }
}

# A zip archive whose files are all in one top directory, unpacked as $SourceDir.
function Download-Zip([string]$Url) {
    $zip = Join-Path ([IO.Path]::GetTempPath()) "pense-bete-$([guid]::NewGuid()).zip"
    $unpacked = "$zip.d"
    try {
        Save-Url $Url $zip
        # Unpacked by .NET, much faster than Expand-Archive.
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($zip, $unpacked)
        $top = @(Get-ChildItem -LiteralPath $unpacked -Directory)[0].FullName
        Move-Item -LiteralPath $top -Destination $SourceDir
    } finally {
        Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $unpacked -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Require-Api {
    $api = GitHub-Api
    if (-not $api) {
        Fail (T "Downloading from {0} needs git." "Le t\u00e9l\u00e9chargement depuis {0} n\u00e9cessite git." $RepoUrl)
    }
    return $api
}

# Without git: the newest release's source archive, its tag and commit recorded for the
# installation.
function Download-Release {
    $api = Require-Api
    Info (T "Downloading the newest release of {0} from {1}" "T\u00e9l\u00e9chargement de la derni\u00e8re version de {0} depuis {1}" @($AppName, $RepoUrl))
    try {
        $tag = Newest-Tag $api
        Download-Zip $tag.zipball_url
    } catch {
        Fail (T "Could not download the application: {0}" "Impossible de t\u00e9l\u00e9charger l'application : {0}" "$_")
    }
    $script:Release = $tag.name
    $script:Commit = $tag.commit.sha
    Info (T "{0} {1} downloaded" "{0} {1} t\u00e9l\u00e9charg\u00e9" @($AppName, $Release))
}

# The newest release's standalone build, attached to its GitHub release.
function Download-Bundle {
    $api = Require-Api
    Info (T "Downloading the standalone version of {0} from {1}" "T\u00e9l\u00e9chargement de la version autonome de {0} depuis {1}" @($AppName, $RepoUrl))
    try {
        $tag = Newest-Tag $api
        # Not $release: PowerShell names are case-insensitive, and that one would hide
        # the script's $Release.
        $githubRelease = Invoke-RestMethod -Uri "$api/releases/tags/$($tag.name)" -Headers @{ "User-Agent" = "pense-bete" } -UseBasicParsing
        $asset = @($githubRelease.assets | Where-Object { $_.name -eq $BundleAsset })[0]
    } catch {
        $asset = $null
    }
    # The build runs for a few minutes after a release is tagged.
    if (-not $asset) {
        Fail (T "The standalone version of {0} is not available yet: try again in a few minutes, or install Python." "La version autonome de {0} n'est pas encore disponible : r\u00e9essayez dans quelques minutes, ou installez Python." $tag.name)
    }
    try {
        Download-Zip $asset.browser_download_url
    } catch {
        Fail (T "Could not download the application: {0}" "Impossible de t\u00e9l\u00e9charger l'application : {0}" "$_")
    }
    $script:Release = $tag.name
    $script:Commit = $tag.commit.sha
    Info (T "{0} {1} downloaded" "{0} {1} t\u00e9l\u00e9charg\u00e9" @($AppName, $Release))
}

function Check-Dependencies {
    # Only a warning: without git, notes are saved without history.
    $script:HasGit = [bool](Get-Command git -ErrorAction SilentlyContinue)
    if (-not $HasGit) {
        Warn (T "git is not installed: notes will be saved without history. Install it to keep it: https://git-scm.com/download/win" "git n'est pas install\u00e9 : les post-its seront sauvegard\u00e9s sans historique. Installez-le pour le garder : https://git-scm.com/download/win")
    }
    # A standalone build to install, as the application's own update hands over.
    if ($SourceDir -and (Test-Path -LiteralPath (Join-Path $SourceDir $Executable))) {
        $script:Bundle = $true
        return
    }
    $script:Python = Find-Python
    if (-not $SourceDir -and ($Standalone -or (-not $Python -and (AskYes (T "Python is not installed. Install the standalone version, which carries it (about 40 MB)?" "Python n'est pas install\u00e9. Installer la version autonome, qui l'inclut (environ 40 Mo) ?"))))) {
        $script:SourceDir = Join-Path ([IO.Path]::GetTempPath()) "pense-bete-$([guid]::NewGuid())"
        $script:Cleanup = $SourceDir
        Download-Bundle
        $script:Bundle = $true
        return
    }
    if (-not $Python) {
        Fail (T "Python 3 not found. Install it from https://www.python.org/downloads/ then run this again." "Python 3 est introuvable. Installez-le depuis https://www.python.org/downloads/ puis relancez.")
    }

    if (-not $SourceDir -and -not $HasGit) {
        $script:SourceDir = Join-Path ([IO.Path]::GetTempPath()) "pense-bete-$([guid]::NewGuid())"
        $script:Cleanup = $SourceDir
        Download-Release
    } elseif (-not $SourceDir) {
        $script:SourceDir = Join-Path ([IO.Path]::GetTempPath()) "pense-bete-$([guid]::NewGuid())"
        $script:Cleanup = $SourceDir
        $newest = Latest-Release
        $branch = @()
        if ($newest) {
            Info (T "Downloading {0} {1} from {2}" "T\u00e9l\u00e9chargement de {0} {1} depuis {2}" @($AppName, $newest, $RepoUrl))
            $branch = @("--branch", $newest)
        } else {
            Warn (T "{0} has no release yet: installing its latest commit." "{0} n'a encore aucune version publi\u00e9e : installation de son dernier commit." $RepoUrl)
        }
        Native "git" (@("clone", "--quiet", "--depth", "1") + $branch + @("--", $RepoUrl, $SourceDir)) | Out-Null
        if ($LASTEXITCODE) { Fail (T "Could not download the application." "Impossible de t\u00e9l\u00e9charger l'application.") }
    }
    # Checked before anything is copied, so that a release from before Windows was
    # supported leaves nothing half installed.
    $missing = @($Files | Where-Object { -not (Test-Path -LiteralPath (Join-Path $SourceDir $_)) })
    if ($missing.Count) {
        Fail (T "This version does not run on Windows yet (missing: {0})." "Cette version ne fonctionne pas encore sous Windows (il manque : {0})." ($missing -join ", "))
    }

    Native $Python @("-c", "import PySide6") | Out-Null
    if ($LASTEXITCODE -eq 0) { return }
    Warn (T "The PySide6 library is not installed." "La biblioth\u00e8que PySide6 n'est pas install\u00e9e.")
    if (AskYes (T "Install it now with pip?" "L'installer maintenant avec pip ?")) {
        & $Python -m pip install --user -r (Join-Path $SourceDir "requirements.txt")
        if ($LASTEXITCODE -eq 0) { return }
        Warn (T "Installation with pip failed." "L'installation avec pip a \u00e9chou\u00e9.")
    }
    Fail (T "Install PySide6-Essentials (py -m pip install PySide6-Essentials), then run this again." "Installez PySide6-Essentials (py -m pip install PySide6-Essentials) puis relancez.")
}

# The shortcut's AppUserModelID, which the application also gives its windows: the
# taskbar then groups them under this entry, and pinning them pins the shortcut rather
# than Python itself. No cmdlet sets it, hence the property store through C#.
$ShortcutIdSource = @"
using System;
using System.Runtime.InteropServices;

[ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPropertyStore {
    void GetCount(out uint count);
    void GetAt(uint index, out PropertyKey key);
    void GetValue(ref PropertyKey key, out PropVariant value);
    void SetValue(ref PropertyKey key, ref PropVariant value);
    void Commit();
}

[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct PropertyKey { public Guid FormatId; public uint PropertyId; }

[StructLayout(LayoutKind.Explicit)]
public struct PropVariant {
    [FieldOffset(0)] public ushort Type;
    [FieldOffset(8)] public IntPtr Pointer;
}

public static class PenseBeteShortcut {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    static extern void SHGetPropertyStoreFromParsingName(string path, IntPtr context, int flags,
        ref Guid interfaceId, [MarshalAs(UnmanagedType.Interface)] out IPropertyStore store);

    public static void SetAppId(string path, string appId) {
        Guid interfaceId = new Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99");
        IPropertyStore store;
        SHGetPropertyStoreFromParsingName(path, IntPtr.Zero, 2 /* read-write */, ref interfaceId, out store);
        PropertyKey key = new PropertyKey();
        key.FormatId = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");  // System.AppUserModel.ID
        key.PropertyId = 5;
        PropVariant value = new PropVariant();
        value.Type = 31;  // a UTF-16 string
        value.Pointer = Marshal.StringToCoTaskMemUni(appId);
        try { store.SetValue(ref key, ref value); store.Commit(); }
        finally { Marshal.FreeCoTaskMem(value.Pointer); Marshal.ReleaseComObject(store); }
    }
}
"@

# What starts the installed application: its executable, or pythonw, which runs it
# without a console window, on its script.
function Launcher([string]$InstallDir) {
    if ($Bundle) { return @("$InstallDir\$Executable", "") }
    $pythonw = Join-Path (Split-Path $Python) "pythonw.exe"
    if (-not (Test-Path -LiteralPath $pythonw)) { $pythonw = $Python }
    return @($pythonw, "`"$InstallDir\pense_bete.py`"")
}

function Write-Shortcut([string]$InstallDir) {
    $launcher = Launcher $InstallDir
    $icon = if ($Dev) { "icon-dev.ico" } else { "icon.ico" }
    New-Item -ItemType Directory -Force -Path (Split-Path $Shortcut) | Out-Null
    $link = (New-Object -ComObject WScript.Shell).CreateShortcut($Shortcut)
    $link.TargetPath = $launcher[0]
    $link.Arguments = $launcher[1]
    $link.WorkingDirectory = $HOME
    $link.IconLocation = "$InstallDir\$icon,0"
    $link.Description = T "Sticky notes versioned with git" "Post-its versionn\u00e9s avec git"
    $link.Save()
    try {
        if (-not ("PenseBeteShortcut" -as [type])) { Add-Type -TypeDefinition $ShortcutIdSource }
        [PenseBeteShortcut]::SetAppId($Shortcut, $AppId)
    } catch {
        Warn (T "The taskbar may show Python's icon for the windows: {0}" "La barre des t\u00e2ches pourrait montrer l'ic\u00f4ne de Python pour les fen\u00eatres : {0}" "$_")
    }
}

function Do-Install {
    $installDir = $Target
    if ($Dev) {
        if (-not $SourceDir -or -not (Test-Path -LiteralPath (Join-Path $SourceDir ".git"))) {
            Fail (T "-Dev runs from a git clone of the repository." "-Dev s'utilise depuis un clone git du d\u00e9p\u00f4t.")
        }
        $installDir = $SourceDir
    }
    Check-Dependencies
    if (-not $installDir) {
        $installDir = Ask (T "Installation directory [{0}]" "Dossier d'installation [{0}]" $DefaultDir)
        if (-not $installDir) { $installDir = $DefaultDir }
    }
    New-Item -ItemType Directory -Force -Path $installDir | Out-Null
    $installDir = (Resolve-Path -LiteralPath $installDir).Path

    if ($installDir -ne (Resolve-Path -LiteralPath $SourceDir).Path) {
        $installed = (Test-Path -LiteralPath (Join-Path $installDir "pense_bete.py")) -or
                     (Test-Path -LiteralPath (Join-Path $installDir $Executable))
        if ((Get-ChildItem -LiteralPath $installDir -Force) -and -not $installed) {
            if (-not (AskYes (T "{0} is not empty, install anyway?" "{0} n'est pas vide, installer quand m\u00eame ?" $installDir))) {
                Fail (T "Installation cancelled." "Installation annul\u00e9e.")
            }
        }
        Info (T "Copying files to {0}" "Copie des fichiers dans {0}" $installDir)
        # What an earlier installation put there goes first, of either kind, so that
        # nothing of an earlier version is left behind, nor of the other kind.
        foreach ($item in @($Files + @($Package, $Executable, "_internal", "icon-dev.ico"))) {
            $path = Join-Path $installDir $item
            if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
        }
        if ($Bundle) {
            Copy-Item -Path (Join-Path $SourceDir "*") -Destination $installDir -Recurse -Force
        } else {
            foreach ($file in $Files) {
                Copy-Item -LiteralPath (Join-Path $SourceDir $file) -Destination $installDir -Force
            }
            $packageDir = Join-Path $installDir $Package
            New-Item -ItemType Directory -Path $packageDir | Out-Null
            Copy-Item -Path (Join-Path $SourceDir "$Package\*.py") -Destination $packageDir
        }
    }
    # The installed commit, which the application compares with the repository to offer
    # updates, and the release it is, when the commit is one, for the About window; given
    # by -Commit and -Release for a copy git cannot tell about, as an archive.
    if (-not (Test-Path -LiteralPath (Join-Path $installDir ".git"))) {
        foreach ($record in @(@(".version", $Commit, @("rev-parse", "HEAD")),
                              @(".release", $Release, @("describe", "--tags", "--exact-match", "--match", "v[0-9]*", "HEAD")))) {
            $path = Join-Path $installDir $record[0]
            $value = $record[1]
            if (-not $value -and $HasGit) {
                $value = Native "git" (@("-C", $SourceDir) + $record[2])
                if ($LASTEXITCODE) { $value = "" }
            }
            if ($value) {
                [IO.File]::WriteAllText($path, "$value".Trim() + "`n")
            } else {
                Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
            }
        }
    }

    Info (T "Adding the entry to the Start menu" "Ajout de l'entr\u00e9e dans le menu D\u00e9marrer")
    Write-Shortcut $installDir

    if ($Launch) {
        $launcher = Launcher $installDir
        $start = @{ FilePath = $launcher[0]; WorkingDirectory = $HOME }
        if ($launcher[1]) { $start.ArgumentList = $launcher[1] }  # none for the executable
        Start-Process @start
    }
    Info (T "{0} is installed in {1}" "{0} est install\u00e9 dans {1}" @($AppName, $installDir))
    Write-Host (T '    Launch it from the Start menu (search for "{0}")' "    Lancez-le depuis le menu D\u00e9marrer (cherchez \u00ab {0} \u00bb)" $AppName)
    $uninstall = "$installDir\install.ps1 -Uninstall$(if ($Dev) { ' -Dev' })"
    Write-Host (T "    To uninstall: {0}" "    D\u00e9sinstallation : {0}" $uninstall)
}

$Cleanup = ""
$HasGit = $false
try {
    # The application hands over and quits: its files can be replaced, or removed, once
    # it has, which Windows forbids while it runs.
    if ($WaitPid) { Wait-Process -Id $WaitPid -Timeout 120 -ErrorAction SilentlyContinue }
    # A download the application unpacked for this installer, which it cannot remove.
    if ($RemoveSource -and $SourceDir) { $Cleanup = $SourceDir }
    if ($Uninstall) { Do-Uninstall } else { Do-Install }
} finally {
    if ($Cleanup) { Remove-Item -LiteralPath $Cleanup -Recurse -Force -ErrorAction SilentlyContinue }
}
