Option Explicit
Dim shell, files, base, command, start, parent, matches, visited, capped, locateOnly, arg, choices, key, pick, index
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
Set matches = CreateObject("Scripting.Dictionary")
matches.CompareMode = 1
visited = 0 : capped = False : locateOnly = False
For Each arg In WScript.Arguments
  If LCase(arg) = "/locate" Then locateOnly = True
Next
start = files.GetParentFolderName(WScript.ScriptFullName)
parent = files.GetParentFolderName(start)
If IsStudio(start) Then
  base = start
ElseIf IsStudio(parent) Then
  base = parent
Else
  FindStudios parent, 0
  If capped Then
    Fail "The bounded folder search reached 5,000 folders. Put the launcher beside the app, or inside its app folder."
  ElseIf matches.Count = 0 Then
    Fail "No complete app was found beside this launcher, in its parent, or within six subfolder levels. Extract the Portable ZIP or move the launcher closer."
  ElseIf matches.Count = 1 Then
    base = matches.Keys()(0)
  Else
    choices = "More than one Discord Archive Studio folder was found:" & vbCrLf
    index = 0
    For Each key In matches.Keys
      index = index + 1
      choices = choices & vbCrLf & index & ": " & key
    Next
    If locateOnly Then
      WScript.Echo choices
      WScript.Quit 2
    End If
    pick = InputBox(choices & vbCrLf & vbCrLf & "Enter the number of the library to open.", "Choose Discord Archive Studio")
    If pick = "" Then WScript.Quit 0
    If Not IsNumeric(pick) Then Fail "Choose a listed number."
    If CDbl(pick) <> Fix(CDbl(pick)) Or CDbl(pick) < 1 Or CDbl(pick) > matches.Count Then Fail "Choose a listed number."
    base = matches.Keys()(CInt(pick)-1)
  End If
End If
If locateOnly Then
  WScript.Echo base
  WScript.Quit 0
End If
shell.CurrentDirectory = base
command = Chr(34) & base & "\runtime\pythonw.exe" & Chr(34) & " " & Chr(34) & base & "\app.py" & Chr(34)
On Error Resume Next
shell.Run command, 0, False
If Err.Number <> 0 Then
  MsgBox "Could not open the archive: " & Err.Description, vbCritical, "Discord Archive Studio"
  WScript.Quit 1
End If

Function IsStudio(path)
  IsStudio = files.FileExists(path & "\runtime\pythonw.exe") And files.FileExists(path & "\app.py") And files.FileExists(path & "\studio\server.py") And files.FileExists(path & "\web\index.html")
End Function

Sub FindStudios(path, depth)
  Dim folder, child, name
  If capped Or depth > 6 Then Exit Sub
  visited = visited + 1
  If visited > 5000 Then
    capped = True
    Exit Sub
  End If
  On Error Resume Next
  Set folder = files.GetFolder(path)
  If Err.Number <> 0 Then
    Err.Clear
    Exit Sub
  End If
  If (folder.Attributes And 1024) <> 0 Then Exit Sub
  If IsStudio(path) Then
    If Not matches.Exists(path) Then matches.Add path, path
    Exit Sub
  End If
  If depth = 6 Then Exit Sub
  For Each child In folder.SubFolders
    name = LCase(child.Name)
    If name <> "data" And name <> "exports" And name <> "runtime" And name <> ".git" And name <> ".work" And name <> "recovery" And name <> "logs" Then FindStudios child.Path, depth + 1
  Next
  On Error GoTo 0
End Sub

Sub Fail(message)
  If locateOnly Then
    WScript.Echo message
  Else
    MsgBox message, vbCritical, "Discord Archive Studio"
  End If
  WScript.Quit 1
End Sub
