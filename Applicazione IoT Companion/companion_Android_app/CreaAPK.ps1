param(
    [switch]$Release
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AndroidStudioJbr = "C:\Program Files\Android\Android Studio\jbr"
$JavaExe = Join-Path $AndroidStudioJbr "bin\java.exe"

if (-not (Test-Path $JavaExe)) {
    throw "Java di Android Studio non trovato in '$AndroidStudioJbr'. Apri Android Studio o installa il JBR, poi riprova."
}

$env:JAVA_HOME = $AndroidStudioJbr
$env:Path = "$AndroidStudioJbr\bin;$env:Path"

$Task = if ($Release) { ":app:assembleRelease" } else { ":app:assembleDebug" }

Push-Location $ProjectDir
try {
    & .\gradlew.bat $Task
    if ($LASTEXITCODE -ne 0) {
        throw "Gradle ha terminato con codice $LASTEXITCODE."
    }

    $ApkPath = if ($Release) {
        "app\build\outputs\apk\release\app-release.apk"
    } else {
        "app\build\outputs\apk\debug\app-debug.apk"
    }

    Write-Host ""
    Write-Host "APK creato correttamente:" -ForegroundColor Green
    Write-Host (Join-Path $ProjectDir $ApkPath)
} finally {
    Pop-Location
}
