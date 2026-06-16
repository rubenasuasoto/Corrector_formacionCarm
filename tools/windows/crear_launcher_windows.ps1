param(
    [string]$Salida = "Corrector CARM.exe"
)

$ErrorActionPreference = "Stop"
$ToolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = [IO.Path]::GetFullPath((Join-Path $ToolsDir "..\.."))
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
            string pythonw = Path.Combine(root, ".venv", "Scripts", "pythonw.exe");
            string python = Path.Combine(root, ".venv", "Scripts", "python.exe");
            string runner = File.Exists(pythonw) ? pythonw : python;
            string app = Path.Combine(root, "interfaz_app.py");

            if (!File.Exists(runner))
            {
                MessageBox.Show(
                    "No se encontro el entorno de Python de la app. Reinstala Corrector CARM o ejecuta el reparador de dependencias.",
                    "Corrector CARM",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
                return;
            }

            if (!File.Exists(app))
            {
                MessageBox.Show(
                    "No se encontro interfaz_app.py junto al lanzador. Reinstala o extrae el paquete completo.",
                    "Corrector CARM",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
                return;
            }

            EnsureEnvTemplate(root);

            string extraArgs = BuildExtraArgs(args);
            string appArgs = QuoteArg(app) + " --tray --host 127.0.0.1 --port 8765" + extraArgs;

            var psi = new ProcessStartInfo
            {
                FileName = runner,
                Arguments = appArgs,
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

        private static void EnsureEnvTemplate(string root)
        {
            string env = Path.Combine(root, ".env");
            string example = Path.Combine(root, ".env.example");
            if (!File.Exists(env) && File.Exists(example))
            {
                File.Copy(example, env);
            }
        }

        private static bool HasArg(string[] args, string name)
        {
            if (args == null)
            {
                return false;
            }
            foreach (string arg in args)
            {
                if (string.Equals(arg, name, StringComparison.OrdinalIgnoreCase))
                {
                    return true;
                }
            }
            return false;
        }

        private static string BuildExtraArgs(string[] args)
        {
            if (args == null || args.Length == 0)
            {
                return "";
            }
            string output = "";
            foreach (string arg in args)
            {
                if (string.Equals(arg, "--no-browser", StringComparison.OrdinalIgnoreCase))
                {
                    output += " --no-browser";
                }
                else if (string.Equals(arg, "-AutoPreparar", StringComparison.OrdinalIgnoreCase) || string.Equals(arg, "--auto-correct", StringComparison.OrdinalIgnoreCase))
                {
                    output += " --auto-correct";
                }
                else if (string.Equals(arg, "-SinEscaneoInicial", StringComparison.OrdinalIgnoreCase) || string.Equals(arg, "--no-startup-scan", StringComparison.OrdinalIgnoreCase))
                {
                    output += " --no-startup-scan";
                }
            }
            return output;
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
