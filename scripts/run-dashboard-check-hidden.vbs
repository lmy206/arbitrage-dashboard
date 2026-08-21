Option Explicit

Dim fileSystem, shell, scriptDirectory, powerShellScript, command

Set fileSystem = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDirectory = fileSystem.GetParentFolderName(WScript.ScriptFullName)
powerShellScript = fileSystem.BuildPath(scriptDirectory, "start-dashboard.ps1")
command = "powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " & _
  Chr(34) & powerShellScript & Chr(34) & " -Port 3001"

' Window style 0 runs the health check without creating a visible terminal.
shell.Run command, 0, True
