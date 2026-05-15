param(
    [string]$Salida = "Corrector CARM.exe"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

function Write-Step($Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

$IconPath = Join-Path $Root "assets\corrector_carm.ico"
if (-not (Test-Path -LiteralPath $IconPath)) {
    throw "No se encontro el icono de la app: $IconPath"
}

$OutputPath = [IO.Path]::GetFullPath((Join-Path $Root $Salida))
$Source = @"
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

namespace CorrectorCarmLauncher
{
    internal static class Program
    {
        [STAThread]
        private static void Main(string[] args)
        {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string script = Path.Combine(root, "iniciar_app_windows.ps1");
            if (!File.Exists(script))
            {
                MessageBox.Show(
                    "No se encontro iniciar_app_windows.ps1 junto al lanzador. Reinstala o extrae el paquete completo.",
                    "Corrector CARM",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
                return;
            }

            string extraArgs = "";
            if (args != null && args.Length > 0)
            {
                extraArgs = " " + string.Join(" ", Array.ConvertAll(args, QuoteArg));
            }

            var psi = new ProcessStartInfo
            {
                FileName = "powershell.exe",
                Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " + QuoteArg(script) + " -AbrirNavegador" + extraArgs,
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            };

            try
            {
                Process.Start(psi);
            }
            catch (Exception ex)
            {
                MessageBox.Show(
                    "No se pudo iniciar Corrector CARM:\n" + ex.Message,
                    "Corrector CARM",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
            }
        }

        private static string QuoteArg(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return "\"\"";
            }
            return "\"" + value.Replace("\"", "\\\"") + "\"";
        }
    }
}
"@

Write-Step "Compilando lanzador de Windows"
$Provider = New-Object Microsoft.CSharp.CSharpCodeProvider
$Params = New-Object System.CodeDom.Compiler.CompilerParameters
$Params.GenerateExecutable = $true
$Params.OutputAssembly = $OutputPath
$Params.TreatWarningsAsErrors = $false
$Params.CompilerOptions = "/target:winexe /win32icon:`"$IconPath`""
[void]$Params.ReferencedAssemblies.Add("System.dll")
[void]$Params.ReferencedAssemblies.Add("System.Windows.Forms.dll")
[void]$Params.ReferencedAssemblies.Add("System.Drawing.dll")

$Result = $Provider.CompileAssemblyFromSource($Params, $Source)
if ($Result.Errors.Count -gt 0) {
    $Messages = @()
    foreach ($ErrorItem in $Result.Errors) {
        $Messages += "$($ErrorItem.FileName):$($ErrorItem.Line):$($ErrorItem.Column): $($ErrorItem.ErrorText)"
    }
    throw "No se pudo compilar el lanzador:`n$($Messages -join "`n")"
}

Write-Host ""
Write-Host "Lanzador creado: $OutputPath" -ForegroundColor Green
