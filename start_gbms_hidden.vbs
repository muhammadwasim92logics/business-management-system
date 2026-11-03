Set WshShell = CreateObject("WScript.Shell")
projectPath = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
scriptPath = projectPath & "start_gbms.ps1"
command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & scriptPath & """"

WshShell.Run command, 0, False
