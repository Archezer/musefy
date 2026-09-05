using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;

internal static class MusefyLauncher
{
    private const string AppUserModelId = "Archezer.Musefy";
    private const ushort VariantTypeWideString = 31;

    [ComImport]
    [Guid("00021401-0000-0000-C000-000000000046")]
    [ClassInterface(ClassInterfaceType.None)]
    private class ShellLinkClass
    {
    }

    [ComImport]
    [Guid("000214F9-0000-0000-C000-000000000046")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IShellLinkW
    {
        void GetPath(
            [Out, MarshalAs(UnmanagedType.LPWStr)]
            System.Text.StringBuilder path,
            int maxPath,
            IntPtr fileData,
            int flags
        );

        void GetIDList(out IntPtr itemIdList);

        void SetIDList(IntPtr itemIdList);

        void GetDescription(
            [Out, MarshalAs(UnmanagedType.LPWStr)]
            System.Text.StringBuilder description,
            int maxDescription
        );

        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string description);

        void GetWorkingDirectory(
            [Out, MarshalAs(UnmanagedType.LPWStr)]
            System.Text.StringBuilder directory,
            int maxDirectory
        );

        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string directory);

        void GetArguments(
            [Out, MarshalAs(UnmanagedType.LPWStr)]
            System.Text.StringBuilder arguments,
            int maxArguments
        );

        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string arguments);

        void GetHotkey(out short hotkey);

        void SetHotkey(short hotkey);

        void GetShowCmd(out int showCommand);

        void SetShowCmd(int showCommand);

        void GetIconLocation(
            [Out, MarshalAs(UnmanagedType.LPWStr)]
            System.Text.StringBuilder iconPath,
            int maxIconPath,
            out int iconIndex
        );

        void SetIconLocation(
            [MarshalAs(UnmanagedType.LPWStr)] string iconPath,
            int iconIndex
        );

        void SetRelativePath(
            [MarshalAs(UnmanagedType.LPWStr)] string relativePath,
            int reserved
        );

        void Resolve(IntPtr windowHandle, int flags);

        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string path);
    }

    [ComImport]
    [Guid("0000010B-0000-0000-C000-000000000046")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IPersistFile
    {
        void GetClassID(out Guid classId);

        [PreserveSig]
        int IsDirty();

        void Load([MarshalAs(UnmanagedType.LPWStr)] string fileName, int mode);

        void Save(
            [MarshalAs(UnmanagedType.LPWStr)] string fileName,
            [MarshalAs(UnmanagedType.Bool)] bool remember
        );

        void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string fileName);

        void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string fileName);
    }

    [ComImport]
    [Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IPropertyStore
    {
        void GetCount(out uint count);

        void GetAt(uint index, out PropertyKey key);

        void GetValue(ref PropertyKey key, out PropVariant value);

        void SetValue(ref PropertyKey key, ref PropVariant value);

        void Commit();
    }

    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    private struct PropertyKey
    {
        public Guid FormatId;
        public uint PropertyId;
    }

    [StructLayout(LayoutKind.Explicit)]
    private struct PropVariant
    {
        [FieldOffset(0)]
        public ushort VariantType;

        [FieldOffset(8)]
        public IntPtr PointerValue;

        [FieldOffset(8)]
        public long ForceSize;
    }

    [DllImport(
        "shell32.dll",
        CharSet = CharSet.Unicode,
        ExactSpelling = true
    )]
    private static extern int SetCurrentProcessExplicitAppUserModelID(
        [MarshalAs(UnmanagedType.LPWStr)] string appId
    );

    [DllImport("ole32.dll")]
    private static extern int PropVariantClear(ref PropVariant value);

    [STAThread]
    private static int Main(string[] args)
    {
        SetCurrentProcessExplicitAppUserModelID(AppUserModelId);

        string root = AppDomain.CurrentDomain.BaseDirectory;
        if (args.Length == 1 && args[0] == "--create-shortcuts")
        {
            try
            {
                CreateShortcuts(root);
                return 0;
            }
            catch (Exception error)
            {
                return ShowError(
                    "Musefy shortcuts could not be created:\n" + error.Message
                );
            }
        }

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

    private static void CreateShortcuts(string root)
    {
        string target = Path.Combine(root, "Musefy.exe");
        string icon = Path.Combine(root, "assets", "musefy-mark.ico");
        string startMenu = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.StartMenu),
            "Programs",
            "Musefy.lnk"
        );
        string desktop = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
            "Musefy.lnk"
        );

        foreach (string location in new[] { startMenu, desktop })
        {
            CreateShortcut(location, target, root, icon);
        }
    }

    private static void CreateShortcut(
        string location,
        string target,
        string workingDirectory,
        string icon
    )
    {
        string parent = Path.GetDirectoryName(location);
        if (!string.IsNullOrEmpty(parent))
        {
            Directory.CreateDirectory(parent);
        }

        IShellLinkW link = (IShellLinkW)new ShellLinkClass();
        try
        {
            link.SetPath(target);
            link.SetWorkingDirectory(workingDirectory);
            link.SetDescription("Musefy music recommendation app");
            link.SetIconLocation(icon, 0);
            link.SetShowCmd(1);
            try
            {
                SetShortcutAppUserModelId(link);
            }
            catch (Exception error)
            {
                throw new InvalidOperationException(
                    "Could not set shortcut AppUserModelID: " + error.Message,
                    error
                );
            }

            try
            {
                ((IPersistFile)link).Save(location, true);
            }
            catch (Exception error)
            {
                throw new InvalidOperationException(
                    "Could not save shortcut: " + error.Message,
                    error
                );
            }
        }
        finally
        {
            Marshal.ReleaseComObject(link);
        }
    }

    private static void SetShortcutAppUserModelId(IShellLinkW link)
    {
        IPropertyStore propertyStore = (IPropertyStore)link;
        PropertyKey appIdKey = new PropertyKey
        {
            FormatId = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"),
            PropertyId = 5,
        };
        IntPtr appIdPointer = Marshal.StringToCoTaskMemUni(AppUserModelId);
        PropVariant appIdValue = new PropVariant
        {
            VariantType = VariantTypeWideString,
            PointerValue = appIdPointer,
        };

        try
        {
            propertyStore.SetValue(ref appIdKey, ref appIdValue);
            propertyStore.Commit();
        }
        finally
        {
            PropVariantClear(ref appIdValue);
        }
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
