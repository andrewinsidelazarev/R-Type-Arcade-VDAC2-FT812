# Снимок окна вывода FT812 через PrintWindow.
#
# У эмулятора несколько окон: EMUL_WND (экран ZX, 720x576), DEBUG_WND,
# VISUALS_WND и FT_WND — окно VDAC2 1024x768, куда рисует FT812. Именно оно и
# нужно; MainWindowHandle отдаёт EMUL_WND, поэтому окно ищется перебором по
# классу FT_WND среди окон процесса.
#
# CopyFromScreen в RDP падает с "handle is invalid", а ft812_dump.bmp патч
# пишет однократно при старте и у R-Type всегда ловит ещё пустой экран.
param(
  [string]$Out = "screen.png",
  [int]$ProcessId = 0
)
if (-not ("W" -as [type])) {
Add-Type @"
using System; using System.Runtime.InteropServices; using System.Text;
public class W {
  public delegate bool Cb(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] public static extern bool EnumWindows(Cb cb, IntPtr p);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out R r);
  public struct R { public int L, T, Rt, B; }
  public static IntPtr Ft(uint target) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((h, p) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      if (pid == target) {
        var c = new StringBuilder(64); GetClassNameW(h, c, 64);
        if (c.ToString() == "FT_WND") { found = h; return false; }
      }
      return true;
    }, IntPtr.Zero);
    return found;
  }
}
"@
}
Add-Type -AssemblyName System.Drawing
$p = if ($ProcessId) {
  Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
} else {
  Get-Process Unreal -ErrorAction SilentlyContinue | Select-Object -First 1
}
if (-not $p) { "эмулятор не запущен"; exit 1 }
$h = [W]::Ft([uint32]$p.Id)
if ($h -eq [IntPtr]::Zero) { "окно FT_WND не найдено"; exit 1 }
$r = New-Object W+R
[void][W]::GetClientRect($h, [ref]$r)
$bmp = New-Object Drawing.Bitmap $r.Rt, $r.B
$g = [Drawing.Graphics]::FromImage($bmp)
$dc = $g.GetHdc()
# PW_CLIENTONLY | PW_RENDERFULLCONTENT: без заголовка окна, иначе нижние строки кадра обрезаются.
[void][W]::PrintWindow($h, $dc, 3)
$g.ReleaseHdc($dc); $g.Dispose()
$bmp.Save($Out); $bmp.Dispose()
"снято: $Out ($($r.Rt)x$($r.B))"
