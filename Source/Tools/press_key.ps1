# Нажатие клавиши в эмуляторе для проверки сборки: окно EMUL_WND процесса выводится
# на передний план, клавиша отправляется через SendInput скан-кодом (эмулятор читает
# клавиатуру через DirectInput, сообщения WM_KEYDOWN он не видит).
#
# Скан-коды set-1: Space 0x39, Enter 0x1C, Q 0x10, A 0x1E, O 0x18, P 0x19, N 0x31,
# F9 0x43, ` 0x29; модификатор (-Modifier): Alt 0x38, Ctrl 0x1D, Shift 0x2A.
param(
  [int]$ProcessId = 0,
  [int]$Scan = 0x39,
  [int]$Modifier = 0,
  [int]$HoldMs = 300
)
if (-not ("K" -as [type])) {
Add-Type @"
using System; using System.Runtime.InteropServices; using System.Text;
public class K {
  public delegate bool Cb(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] public static extern bool EnumWindows(Cb cb, IntPtr p);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern void SwitchToThisWindow(IntPtr h, bool alt);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool attach);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  public static bool Front(IntPtr h) {
    uint pid;
    uint mine = GetCurrentThreadId();
    uint other = GetWindowThreadProcessId(GetForegroundWindow(), out pid);
    AttachThreadInput(mine, other, true);
    ShowWindow(h, 9);
    bool done = SetForegroundWindow(h);
    AttachThreadInput(mine, other, false);
    if (!done || GetForegroundWindow() != h) {
      // Windows не отдаёт передний план чужому процессу, если вызывающий сам не на переднем плане
      // (блокировка foreground lock). SwitchToThisWindow переключает окно как Alt+Tab и работает.
      SwitchToThisWindow(h, true);
      BringWindowToTop(h);
      done = (GetForegroundWindow() == h);
    }
    return done;
  }
  [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT { public ushort vk; public ushort scan; public uint flags; public uint time; public IntPtr extra; }
  [StructLayout(LayoutKind.Explicit, Size=40)] public struct INPUT { [FieldOffset(0)] public uint type; [FieldOffset(8)] public KEYBDINPUT ki; }
  [DllImport("user32.dll", SetLastError=true)] public static extern uint SendInput(uint n, INPUT[] inputs, int size);
  public static IntPtr Find(uint target, string cls) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((h, p) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      if (pid == target) {
        var c = new StringBuilder(64); GetClassNameW(h, c, 64);
        if (c.ToString() == cls) { found = h; return false; }
      }
      return true;
    }, IntPtr.Zero);
    return found;
  }
  public static uint Key(ushort scan, bool up) {
    var input = new INPUT[1];
    input[0].type = 1;
    input[0].ki.scan = scan;
    input[0].ki.flags = 8u | (up ? 2u : 0u);   // KEYEVENTF_SCANCODE, KEYEVENTF_KEYUP
    return SendInput(1, input, Marshal.SizeOf(typeof(INPUT)));
  }
}
"@
}
$p = if ($ProcessId) {
  Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
} else {
  Get-Process Unreal -ErrorAction SilentlyContinue | Select-Object -First 1
}
if (-not $p) { "эмулятор не запущен"; exit 1 }
$h = [K]::Find([uint32]$p.Id, "EMUL_WND")
if ($h -eq [IntPtr]::Zero) { "окно EMUL_WND не найдено"; exit 1 }
# Очередь ввода переднего окна временно присоединяется, иначе Windows не отдаёт фокус.
[void][K]::Front($h)
Start-Sleep -Milliseconds 200
if ([K]::GetForegroundWindow() -ne $h) { "окно эмулятора не вышло на передний план, клавиша не отправлена"; exit 1 }
$sent = 0
if ($Modifier) { $sent += [K]::Key([uint16]$Modifier, $false); Start-Sleep -Milliseconds 60 }
$sent += [K]::Key([uint16]$Scan, $false)
Start-Sleep -Milliseconds $HoldMs
$sent += [K]::Key([uint16]$Scan, $true)
if ($Modifier) { Start-Sleep -Milliseconds 60; $sent += [K]::Key([uint16]$Modifier, $true) }
"клавиша 0x$('{0:X2}' -f $Scan): отправлено событий $sent"
