Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = folder

venvPythonw = folder & "\.venv\Scripts\pythonw.exe"
venvPython = folder & "\.venv\Scripts\python.exe"

If fso.FileExists(venvPythonw) Then
  exe = venvPythonw
ElseIf fso.FileExists(venvPython) Then
  exe = venvPython
Else
  exe = "pythonw.exe"
End If

' 0 = hide console. pythonw has no console; python.exe fallback stays hidden too.
cmd = """" & exe & """ -m palworld_admin gui"
sh.Run cmd, 0, False
