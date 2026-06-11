' Lanza el guardián del bot SIN ventana (el Programador de tareas ejecuta esto
' con wscript.exe, que no abre consola; el 0 = ventana oculta).
Set shell = CreateObject("Wscript.Shell")
shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""D:\Proyectos\Botrader\scripts\ensure_bot_running.ps1""", 0, False
