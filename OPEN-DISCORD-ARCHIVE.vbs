Option Explicit
Dim shell, files, base, command
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
base = files.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = base
If Not files.FileExists(base & "\runtime\pythonw.exe") Or Not files.FileExists(base & "\app.py") Then
  MsgBox "Extract the entire Portable ZIP first, then open this launcher from the extracted folder.", vbCritical, "Discord Archive Studio"
  WScript.Quit 1
End If
command = Chr(34) & base & "\runtime\pythonw.exe" & Chr(34) & " " & Chr(34) & base & "\app.py" & Chr(34)
On Error Resume Next
shell.Run command, 0, False
If Err.Number <> 0 Then
  MsgBox "Could not open the archive: " & Err.Description, vbCritical, "Discord Archive Studio"
  WScript.Quit 1
End If
