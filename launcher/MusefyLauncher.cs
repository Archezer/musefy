using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;

internal static class MusefyLauncher
{
    private const string AppUserModelId = "Archezer.Musefy";

    [DllImport(
        "shell32.dll",
        CharSet = CharSet.Unicode,
        ExactSpelling = true
    )]
    private static extern int SetCurrentProcessExplicitAppUserModelID(
        string appId
    );

    [STAThread]
    private static int Main()
    {
        SetCurrentProcessExplicitAppUserModelID(AppUserModelId);

        string root = AppDomain.CurrentDomain.BaseDirectory;
        string pythonw = Path.Combine(root, ".venv", "Scripts", "pythonw.exe");
        if (!File.Exists(pythonw))
        {
            return ShowError(
                "Musefy is not installed correctly. Run install_musefy.bat again."
            );
        }

        ProcessStartInfo startInfo = new ProcessStartInfo
        {
            FileName = pythonw,
            Arguments = "-m app.desktop",
            WorkingDirectory = root,
            UseShellExecute = false,
            CreateNoWindow = true,
        };

        try
        {
            using (Process process = Process.Start(startInfo))
            {
                if (process == null)
                {
                    return ShowError("Musefy could not be started.");
                }

                process.WaitForExit();
            }
        }
        catch (Exception error)
        {
            return ShowError("Musefy could not be started:\n" + error.Message);
        }

        return 0;
    }

    private static int ShowError(string message)
    {
        MessageBox.Show(
            message,
            "Musefy",
            MessageBoxButtons.OK,
            MessageBoxIcon.Error
        );
        return 1;
    }
}
