# Снимок главного окна процесса (клиентская область) через PrintWindow — для сверки
# кадров Python-версии (окно pygame) с кадрами эмулятора.
param(
  [int]$ProcessId,
  [string]$Out = "window.png"
)
if (-not ("PW" -as [type])) {
Add-Type @"
using System; using System.Runtime.InteropServices;
public class PW {
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out R r);
  public struct R { public int L, T, Rt, B; }
}
"@
}
Add-Type -AssemblyName System.Drawing
$p = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
if (-not $p -or $p.MainWindowHandle -eq [IntPtr]::Zero) { "окно процесса не найдено"; exit 1 }
$h = $p.MainWindowHandle
$r = New-Object PW+R
[void][PW]::GetClientRect($h, [ref]$r)
$bmp = New-Object Drawing.Bitmap $r.Rt, $r.B
$g = [Drawing.Graphics]::FromImage($bmp)
$dc = $g.GetHdc()
# PW_CLIENTONLY | PW_RENDERFULLCONTENT
[void][PW]::PrintWindow($h, $dc, 3)
$g.ReleaseHdc($dc); $g.Dispose()
$bmp.Save($Out); $bmp.Dispose()
"снято: $Out ($($r.Rt)x$($r.B))"
