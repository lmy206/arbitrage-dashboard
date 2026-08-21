Option Explicit

Dim shell, fileSystem, scriptDirectory, powershellScript, command, exitCode
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

scriptDirectory = fileSystem.GetParentFolderName(WScript.ScriptFullName)
powershellScript = fileSystem.BuildPath(scriptDirectory, "update-and-publish.ps1")
command = "powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & powershellScript & """"

exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode
