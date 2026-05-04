param(
    [Parameter(Mandatory=$true)][string]$ImagePath,
    [string]$PreparedPath = ""
)

Add-Type -AssemblyName System.Runtime.WindowsRuntime

function Await-Op($AsyncOperation, [Type]$ResultType) {
    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq 'AsTask' -and
            $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        })[0]
    $typed = $asTaskGeneric.MakeGenericMethod($ResultType)
    $task = $typed.Invoke($null, @($AsyncOperation))
    $task.Wait()
    return $task.Result
}

[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime] | Out-Null

$resolved = (Resolve-Path -LiteralPath $ImagePath).Path
if ($PreparedPath -and (Test-Path -LiteralPath $PreparedPath)) {
    $resolved = (Resolve-Path -LiteralPath $PreparedPath).Path
}
$file = Await-Op ([Windows.Storage.StorageFile]::GetFileFromPathAsync($resolved)) ([Windows.Storage.StorageFile])
$stream = Await-Op ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await-Op ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await-Op ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$lang = [Windows.Globalization.Language]::new("zh-Hans-CN")
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
if ($null -eq $engine) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}
if ($null -eq $engine) {
    throw "Windows OCR engine unavailable"
}
$result = Await-Op ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$lines = @()
foreach ($line in $result.Lines) {
    $lines += $line.Text
}
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$payload = @{
    text = ($lines -join "`n")
    line_count = $lines.Count
    text_angle = $result.TextAngle
}
$payload | ConvertTo-Json -Depth 4
