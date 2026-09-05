using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
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
            StringBuilder path,
            int maxPath,
            IntPtr fileData,
            int flags
        );

        void GetIDList(out IntPtr itemIdList);

        void SetIDList(IntPtr itemIdList);

        void GetDescription(
            [Out, MarshalAs(UnmanagedType.LPWStr)]
            StringBuilder description,
            int maxDescription
        );

        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string description);

        void GetWorkingDirectory(
            [Out, MarshalAs(UnmanagedType.LPWStr)]
            StringBuilder directory,
            int maxDirectory
        );

        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string directory);

        void GetArguments(
            [Out, MarshalAs(UnmanagedType.LPWStr)]
            StringBuilder arguments,
            int maxArguments
        );

        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string arguments);

        void GetHotkey(out short hotkey);

        void SetHotkey(short hotkey);

        void GetShowCmd(out int showCommand);

        void SetShowCmd(int showCommand);

        void GetIconLocation(
            [Out, MarshalAs(UnmanagedType.LPWStr)]
            StringBuilder iconPath,
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

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void PySetWideStringDelegate(IntPtr value);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void PyInitializeDelegate();

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate int PyFinalizeExDelegate();

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate int PyRunSimpleStringFlagsDelegate(
        IntPtr code,
        IntPtr flags
    );

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void PyErrPrintDelegate();

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

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr LoadLibrary(string fileName);

    [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)]
    private static extern IntPtr GetProcAddress(IntPtr module, string name);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool FreeLibrary(IntPtr module);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool SetDllDirectory(string path);

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

        try
        {
            return RunEmbeddedPython(root);
        }
        catch (Exception error)
        {
            return ShowError("Musefy could not be started:\n" + error.Message);
        }
    }

    private static int RunEmbeddedPython(string root)
    {
        string virtualEnvironment = Path.Combine(root, ".venv");
        string configPath = Path.Combine(virtualEnvironment, "pyvenv.cfg");
        if (!File.Exists(configPath))
        {
            return ShowError(
                "Musefy is not installed correctly. Run install_musefy.bat again."
            );
        }

        string pythonHome = ReadPythonHome(configPath);
        string pythonDllPath = Path.Combine(pythonHome, "python312.dll");
        if (!File.Exists(pythonDllPath))
        {
            return ShowError(
                "The managed Python runtime is incomplete. Run install_musefy.bat again."
            );
        }

        string sitePackages = Path.Combine(
            virtualEnvironment,
            "Lib",
            "site-packages"
        );
        string scripts = Path.Combine(virtualEnvironment, "Scripts");
        string oldPath = Environment.GetEnvironmentVariable("PATH") ?? "";
        Environment.SetEnvironmentVariable(
            "PATH",
            string.Join(
                Path.PathSeparator.ToString(),
                new[] { scripts, pythonHome, Path.Combine(pythonHome, "DLLs"), oldPath }
            )
        );
        Environment.SetEnvironmentVariable("VIRTUAL_ENV", virtualEnvironment);

        if (!SetDllDirectory(pythonHome))
        {
            throw new InvalidOperationException(
                "Could not configure the managed Python runtime directory."
            );
        }

        IntPtr pythonModule = LoadLibrary(pythonDllPath);
        if (pythonModule == IntPtr.Zero)
        {
            throw new InvalidOperationException(
                "Could not load python312.dll."
            );
        }

        try
        {
            PySetWideStringDelegate setPath = LoadPythonFunction<PySetWideStringDelegate>(
                pythonModule,
                "Py_SetPath"
            );
            PySetWideStringDelegate setProgramName = LoadPythonFunction<PySetWideStringDelegate>(
                pythonModule,
                "Py_SetProgramName"
            );
            PyInitializeDelegate initialize = LoadPythonFunction<PyInitializeDelegate>(
                pythonModule,
                "Py_Initialize"
            );
            PyFinalizeExDelegate finalize = LoadPythonFunction<PyFinalizeExDelegate>(
                pythonModule,
                "Py_FinalizeEx"
            );
            PyRunSimpleStringFlagsDelegate runSimpleString = LoadPythonFunction<PyRunSimpleStringFlagsDelegate>(
                pythonModule,
                "PyRun_SimpleStringFlags"
            );
            PyErrPrintDelegate printError = LoadPythonFunction<PyErrPrintDelegate>(
                pythonModule,
                "PyErr_Print"
            );

            IntPtr programName = Marshal.StringToCoTaskMemUni(
                Path.Combine(root, "Musefy.exe")
            );
            IntPtr pythonPath = Marshal.StringToCoTaskMemUni(
                BuildPythonPath(root, pythonHome, sitePackages)
            );
            try
            {
                // CPython keeps these pointers until initialization, so retain
                // the unmanaged strings through the whole interpreter session.
                setProgramName(programName);
                setPath(pythonPath);
                initialize();

                try
                {
                    string code = BuildPythonBootstrap(root, sitePackages);
                    int result = RunUtf8PythonCode(runSimpleString, code);
                    if (result != 0)
                    {
                        printError();
                        return ShowError(
                            "Musefy stopped because its Python application failed."
                        );
                    }
                }
                finally
                {
                    finalize();
                }
            }
            finally
            {
                Marshal.FreeCoTaskMem(programName);
                Marshal.FreeCoTaskMem(pythonPath);
            }
        }
        finally
        {
            FreeLibrary(pythonModule);
            SetDllDirectory(null);
        }

        return 0;
    }

    private static string ReadPythonHome(string configPath)
    {
        foreach (string line in File.ReadAllLines(configPath))
        {
            const string prefix = "home = ";
            if (line.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                string home = line.Substring(prefix.Length).Trim();
                if (Directory.Exists(home))
                {
                    return home;
                }
            }
        }

        throw new InvalidOperationException(
            "Python home was not found in .venv\\pyvenv.cfg."
        );
    }

    private static string BuildPythonPath(
        string root,
        string pythonHome,
        string sitePackages
    )
    {
        List<string> paths = new List<string>
        {
            root,
            sitePackages,
            Path.Combine(pythonHome, "python312.zip"),
            Path.Combine(pythonHome, "Lib"),
            Path.Combine(pythonHome, "DLLs"),
            pythonHome,
        };
        return string.Join(Path.PathSeparator.ToString(), paths);
    }

    private static string BuildPythonBootstrap(string root, string sitePackages)
    {
        string rootLiteral = PythonStringLiteral(root);
        string sitePackagesLiteral = PythonStringLiteral(sitePackages);
        return string.Join(
            "\n",
            new[]
            {
                "import os, runpy, site, sys",
                "root = " + rootLiteral,
                "site_packages = " + sitePackagesLiteral,
                "os.chdir(root)",
                "sys.path.insert(0, root)",
                "site.addsitedir(site_packages)",
                "try:",
                "    runpy.run_module('app.desktop', run_name='__main__')",
                "except SystemExit:",
                "    pass",
                "",
            }
        );
    }

    private static string PythonStringLiteral(string value)
    {
        return "'"
            + value.Replace("\\", "\\\\").Replace("'", "\\'")
            + "'";
    }

    private static int RunUtf8PythonCode(
        PyRunSimpleStringFlagsDelegate runSimpleString,
        string code
    )
    {
        byte[] bytes = Encoding.UTF8.GetBytes(code + "\0");
        GCHandle handle = GCHandle.Alloc(bytes, GCHandleType.Pinned);
        try
        {
            return runSimpleString(handle.AddrOfPinnedObject(), IntPtr.Zero);
        }
        finally
        {
            handle.Free();
        }
    }

    private static T LoadPythonFunction<T>(IntPtr module, string name)
        where T : class
    {
        IntPtr address = GetProcAddress(module, name);
        if (address == IntPtr.Zero)
        {
            throw new InvalidOperationException(
                "Python function was not found: " + name
            );
        }

        return Marshal.GetDelegateForFunctionPointer(address, typeof(T)) as T;
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
            SetShortcutAppUserModelId(link);
            ((IPersistFile)link).Save(location, true);
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
