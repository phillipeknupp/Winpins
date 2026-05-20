# =============================================================================
# WinPins - Clone leve do DeskPins para Windows
# =============================================================================
# Dependências: pip install pywin32 pystray Pillow
#
# ── Como compilar ─────────────────────────────────────────────────────────────
#
#   PASSO 1 – gere o ícone .ico ANTES de compilar:
#       python winpins.py --export-icon
#
#   PASSO 2 – compile:
#       pyinstaller --onefile --windowed ^
#           --icon=winpins_icon.ico ^
#           --hidden-import=win32api ^
#           --hidden-import=win32con ^
#           --hidden-import=win32gui ^
#           --hidden-import=win32process ^
#           --hidden-import=win32timezone ^
#           --hidden-import=pywintypes ^
#           --hidden-import=pystray._win32 ^
#           --hidden-import=PIL.Image ^
#           --hidden-import=PIL.ImageDraw ^
#           --collect-all=pystray ^
#           --collect-all=PIL ^
#           winpins.py
#
# =============================================================================

import sys
import os
import json
import time
import threading
import ctypes
import ctypes.wintypes
import io
import struct
import traceback
from ctypes import windll, wintypes, byref, c_int, c_uint, c_long, c_ulong, POINTER
from typing import Optional, Dict

# ── Dependências externas ─────────────────────────────────────────────────────
try:
    import win32gui
    import win32con
    import win32api
    import win32process
    import pywintypes
except ImportError:
    ctypes.windll.user32.MessageBoxW(
        0, "Instale pywin32:\n  pip install pywin32", "WinPins – Dependência faltando", 0x10)
    sys.exit(1)

try:
    import pystray
    from pystray import MenuItem as item, Menu
except ImportError:
    ctypes.windll.user32.MessageBoxW(
        0, "Instale pystray:\n  pip install pystray", "WinPins – Dependência faltando", 0x10)
    sys.exit(1)

try:
    from PIL import Image, ImageDraw
except ImportError:
    ctypes.windll.user32.MessageBoxW(
        0, "Instale Pillow:\n  pip install Pillow", "WinPins – Dependência faltando", 0x10)
    sys.exit(1)

# =============================================================================
# CONSTANTES WINAPI
# =============================================================================

HWND_TOPMOST   = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE     = 0x0002
SWP_NOSIZE     = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

SW_RESTORE = 9
SW_SHOW    = 5
SW_SHOWNA  = 8

WS_EX_LAYERED    = 0x00080000
WS_EX_TRANSPARENT= 0x00000020
WS_EX_TOPMOST    = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_POPUP         = c_uint(0x80000000).value   # ← c_uint evita truncamento em ctypes

GWL_EXSTYLE = -20
LWA_COLORKEY = 0x00000001

# WinEvent
EVENT_SYSTEM_MINIMIZESTART = 0x0016
EVENT_OBJECT_DESTROY       = 0x8001
WINEVENT_OUTOFCONTEXT      = 0x0000
WINEVENT_SKIPOWNPROCESS    = 0x0002

IDC_CROSS = 32515

WinEventProc = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.HWND,
    wintypes.LONG,
    wintypes.LONG,
    wintypes.DWORD,
    wintypes.DWORD,
)

# Tipos corretos para 64-bit – evitam OverflowError em callbacks WndProc
_WPARAM  = ctypes.c_size_t
_LPARAM  = ctypes.c_ssize_t
_LRESULT = ctypes.c_ssize_t

# =============================================================================
# CONFIGURAÇÃO / PERSISTÊNCIA
# =============================================================================

CONFIG_PATH = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), "WinPins", "config.json")
ICON_PATH = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), "WinPins", "winpins_icon.ico")


def ensure_config_dir():
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)


def load_config() -> dict:
    ensure_config_dir()
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"protection_enabled": True, "pinned_titles": []}


def save_config(cfg: dict):
    ensure_config_dir()
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# =============================================================================
# GERAÇÃO DE ÍCONE
# =============================================================================

def make_tray_icon(size=64, active=True) -> Image.Image:
    """Ícone de alfinete para a bandeja do sistema."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    bg_color  = (30, 60, 120, 255) if active else (70, 70, 70, 255)
    pin_color = (220, 60, 60, 255) if active else (150, 150, 150, 255)

    margin = 4
    d.ellipse([margin, margin, size - margin, size - margin], fill=bg_color)

    cx     = size // 2
    head_r = size // 5
    head_cy= size // 3
    d.ellipse([cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r], fill=pin_color)
    d.ellipse([cx - head_r + 3, head_cy - head_r + 3, cx - 2, head_cy - 2],
              fill=(255, 200, 200, 180))

    haste_top = head_cy + head_r - 2
    haste_bot = size - margin - 6
    haste_w   = max(2, size // 14)
    d.rectangle([cx - haste_w, haste_top, cx + haste_w, haste_bot], fill=pin_color)
    d.polygon([
        (cx - haste_w - 1, haste_bot),
        (cx + haste_w + 1, haste_bot),
        (cx, haste_bot + 6)
    ], fill=pin_color)

    return img


def save_icon_file(path: str):
    """
    Salva o ícone como .ico multi-resolução.
    Necessário para o PyInstaller (--icon=) e para o ícone do EXE.
    """
    ensure_config_dir()
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = []
    for s in sizes:
        img = make_tray_icon(s, active=True)
        # ICO exige RGBA ou RGB
        images.append(img.convert("RGBA"))
    # PIL salva .ico com múltiplos tamanhos automaticamente
    images[0].save(path, format="ICO", sizes=[(s, s) for s in sizes],
                   append_images=images[1:])


def get_or_create_icon_path() -> str:
    """Garante que o .ico existe em APPDATA e retorna o caminho."""
    ensure_config_dir()
    if not os.path.exists(ICON_PATH):
        try:
            save_icon_file(ICON_PATH)
        except Exception:
            pass
    return ICON_PATH


# =============================================================================
# OVERLAY VISUAL (mini-janela sobre a barra de título)
# =============================================================================

class PinOverlay:
    """Janela transparente com ícone de alfinete sobre a janela fixada."""

    OVERLAY_W = 20
    OVERLAY_H = 20
    OFFSET_X  = 8
    OFFSET_Y  = 4

    def __init__(self, target_hwnd: int):
        self.target_hwnd = target_hwnd
        self.hwnd: Optional[int] = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            self._create_window()
        except Exception:
            self._stop.set()
            return

        _WM_QUIT = 0x0012
        msg = wintypes.MSG()
        while not self._stop.is_set():
            while windll.user32.PeekMessageW(byref(msg), 0, 0, 0, 1):
                if msg.message == _WM_QUIT:
                    return
                windll.user32.TranslateMessage(byref(msg))
                windll.user32.DispatchMessageW(byref(msg))
            self._reposition()
            self._stop.wait(0.05)

        if self.hwnd:
            try:
                windll.user32.DestroyWindow(self.hwnd)
            except Exception:
                pass
            self.hwnd = None

    def _create_window(self):
        hinstance = windll.kernel32.GetModuleHandleW(None)
        class_name = f"WinPinsOverlay_{self.target_hwnd}"

        WndProcType = ctypes.WINFUNCTYPE(
            _LRESULT, wintypes.HWND, wintypes.UINT, _WPARAM, _LPARAM)

        _DefWindowProc = windll.user32.DefWindowProcW
        _DefWindowProc.restype  = _LRESULT
        _DefWindowProc.argtypes = [wintypes.HWND, wintypes.UINT, _WPARAM, _LPARAM]

        _WM_PAINT   = 0x000F
        _WM_DESTROY = 0x0002

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == _WM_PAINT:
                ps  = ctypes.create_string_buffer(72)
                hdc = windll.user32.BeginPaint(hwnd, ps)
                self._draw_pin_hdc(hdc)
                windll.user32.EndPaint(hwnd, ps)
                return 0
            if msg == _WM_DESTROY:
                return 0
            return _DefWindowProc(hwnd, msg, wparam, lparam)

        self._wnd_proc_cb = WndProcType(wnd_proc)

        class WNDCLASSEX(ctypes.Structure):
            _fields_ = [
                ("cbSize",        ctypes.c_uint),
                ("style",         ctypes.c_uint),
                ("lpfnWndProc",   WndProcType),
                ("cbClsExtra",    ctypes.c_int),
                ("cbWndExtra",    ctypes.c_int),
                ("hInstance",     wintypes.HANDLE),
                ("hIcon",         wintypes.HANDLE),
                ("hCursor",       wintypes.HANDLE),
                ("hbrBackground", wintypes.HANDLE),
                ("lpszMenuName",  wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
                ("hIconSm",       wintypes.HANDLE),
            ]

        wc = WNDCLASSEX()
        wc.cbSize        = ctypes.sizeof(WNDCLASSEX)
        wc.lpfnWndProc   = self._wnd_proc_cb
        wc.hInstance     = hinstance
        wc.hbrBackground = 0
        wc.lpszClassName = class_name
        windll.user32.RegisterClassExW(byref(wc))

        x, y = self._get_position()
        ex_style = (WS_EX_LAYERED | WS_EX_TRANSPARENT |
                    WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)

        hwnd = windll.user32.CreateWindowExW(
            ex_style, class_name, "WinPinsOverlay", WS_POPUP,
            x, y, self.OVERLAY_W, self.OVERLAY_H,
            0, 0, hinstance, 0)

        if not hwnd:
            raise RuntimeError(
                f"CreateWindowExW falhou (erro {windll.kernel32.GetLastError()})")

        self.hwnd = hwnd
        windll.user32.SetLayeredWindowAttributes(hwnd, 0x00000000, 255, LWA_COLORKEY)
        windll.user32.ShowWindow(hwnd, SW_SHOWNA)
        windll.user32.UpdateWindow(hwnd)

    def _draw_pin_hdc(self, hdc):
        try:
            W, H = self.OVERLAY_W, self.OVERLAY_H
            black_brush = windll.gdi32.CreateSolidBrush(0x00000000)
            rc = wintypes.RECT(0, 0, W, H)
            windll.user32.FillRect(hdc, byref(rc), black_brush)
            windll.gdi32.DeleteObject(black_brush)

            cx  = W // 2
            r   = W // 3
            hcy = H // 3

            red_brush = windll.gdi32.CreateSolidBrush(0x002828D2)   # BGR vermelho
            red_pen   = windll.gdi32.CreatePen(0, 1, 0x002828D2)
            old_brush = windll.gdi32.SelectObject(hdc, red_brush)
            old_pen   = windll.gdi32.SelectObject(hdc, red_pen)

            windll.gdi32.Ellipse(hdc, cx - r, hcy - r, cx + r, hcy + r)
            windll.gdi32.Rectangle(hdc, cx - 1, hcy + r - 1, cx + 2, H - 2)

            windll.gdi32.SelectObject(hdc, old_brush)
            windll.gdi32.SelectObject(hdc, old_pen)
            windll.gdi32.DeleteObject(red_brush)
            windll.gdi32.DeleteObject(red_pen)
        except Exception:
            pass

    def _get_position(self):
        try:
            rect = win32gui.GetWindowRect(self.target_hwnd)
            return rect[0] + self.OFFSET_X, rect[1] + self.OFFSET_Y
        except Exception:
            return 0, 0

    def _reposition(self):
        if not self.hwnd:
            return
        try:
            if not win32gui.IsWindow(self.target_hwnd):
                self._stop.set()
                return
            placement = win32gui.GetWindowPlacement(self.target_hwnd)
            if placement[1] == 2:    # minimizado
                windll.user32.ShowWindow(self.hwnd, 0)
            else:
                x, y = self._get_position()
                windll.user32.SetWindowPos(
                    self.hwnd, HWND_TOPMOST,
                    x, y, self.OVERLAY_W, self.OVERLAY_H,
                    SWP_NOACTIVATE | SWP_SHOWWINDOW)
        except Exception:
            pass

    def destroy(self):
        self._stop.set()


# =============================================================================
# GERENCIADOR DE PINS
# =============================================================================

class PinManager:
    """Gerencia janelas fixadas: topmost, proteção Win+D, overlays, persistência."""

    def __init__(self):
        self.cfg = load_config()
        self.pinned: Dict[int, dict] = {}
        self._lock   = threading.Lock()
        self._hooks  = []
        self._hook_cb = None          # referência mantida viva
        self._stop   = threading.Event()

        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

        # NÃO instala hooks aqui – chamado depois pelo pystray setup callback
        # para garantir que o message loop já está ativo na thread correta.

        self._restore_persisted_pins()

    # ── Hooks ──────────────────────────────────────────────────────────────

    def install_hooks(self):
        """
        Instala WinEventHooks.
        DEVE ser chamado a partir da thread que já possui um message loop ativo
        (ex: dentro do pystray setup= callback).
        Com WINEVENT_OUTOFCONTEXT, eventos são entregues via message queue
        da thread instaladora – sem loop ativo, os callbacks nunca disparam.
        """
        self._hook_cb = WinEventProc(self._win_event_proc)

        def install(ev_min, ev_max):
            h = windll.user32.SetWinEventHook(
                ev_min, ev_max, 0, self._hook_cb, 0, 0,
                WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
            if h:
                self._hooks.append(h)

        install(EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZESTART)
        install(EVENT_OBJECT_DESTROY,       EVENT_OBJECT_DESTROY)

    def _win_event_proc(self, hHook, event, hwnd, idObject, idChild, dwThread, dwTime):
        try:
            if event == EVENT_SYSTEM_MINIMIZESTART:
                if hwnd and self._is_pinned(hwnd):
                    if self.cfg.get("protection_enabled", True):
                        threading.Thread(
                            target=self._restore_window, args=(hwnd,), daemon=True).start()
            elif event == EVENT_OBJECT_DESTROY:
                if hwnd and self._is_pinned(hwnd):
                    threading.Thread(
                        target=self._cleanup_pin, args=(hwnd,), daemon=True).start()
        except Exception:
            pass

    def _restore_window(self, hwnd: int):
        try:
            time.sleep(0.05)
            if not win32gui.IsWindow(hwnd):
                return
            if not self._is_pinned(hwnd):
                return
            win32gui.ShowWindow(hwnd, SW_RESTORE)
            windll.user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            pass

    def _cleanup_pin(self, hwnd: int):
        time.sleep(0.1)
        self.unpin(hwnd, silent=True)

    def _is_pinned(self, hwnd: int) -> bool:
        with self._lock:
            return hwnd in self.pinned

    # ── Monitor de integridade ─────────────────────────────────────────────

    def _monitor_loop(self):
        while not self._stop.is_set():
            try:
                with self._lock:
                    hwnds = list(self.pinned.keys())

                for hwnd in hwnds:
                    try:
                        if not win32gui.IsWindow(hwnd):
                            self.unpin(hwnd, silent=True)
                            continue
                        windll.user32.SetWindowPos(
                            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                        if self.cfg.get("protection_enabled", True):
                            placement = win32gui.GetWindowPlacement(hwnd)
                            if placement[1] == 2:
                                self._restore_window(hwnd)
                    except Exception:
                        pass
            except Exception:
                pass

            self._stop.wait(0.5)

    # ── API pública ────────────────────────────────────────────────────────

    def pin(self, hwnd: int) -> bool:
        if not win32gui.IsWindow(hwnd):
            return False
        with self._lock:
            if hwnd in self.pinned:
                return False
        try:
            title = win32gui.GetWindowText(hwnd) or "(sem título)"
        except Exception:
            title = "(sem título)"

        windll.user32.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

        overlay = PinOverlay(hwnd)
        with self._lock:
            self.pinned[hwnd] = {"title": title, "overlay": overlay}
        self._persist()
        return True

    def unpin(self, hwnd: int, silent=False) -> bool:
        with self._lock:
            entry = self.pinned.pop(hwnd, None)
        if entry is None:
            return False
        try:
            if win32gui.IsWindow(hwnd):
                windll.user32.SetWindowPos(
                    hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            pass
        try:
            entry["overlay"].destroy()
        except Exception:
            pass
        if not silent:
            self._persist()
        return True

    def unpin_all(self):
        with self._lock:
            hwnds = list(self.pinned.keys())
        for hwnd in hwnds:
            self.unpin(hwnd)

    def get_pinned_list(self) -> list:
        with self._lock:
            return [(hwnd, d["title"]) for hwnd, d in self.pinned.items()]

    def set_protection(self, enabled: bool):
        self.cfg["protection_enabled"] = enabled
        save_config(self.cfg)

    def is_protection_enabled(self) -> bool:
        return self.cfg.get("protection_enabled", True)

    def _persist(self):
        with self._lock:
            titles = [d["title"] for d in self.pinned.values() if d["title"]]
        self.cfg["pinned_titles"] = titles
        save_config(self.cfg)

    def _restore_persisted_pins(self):
        saved_titles: list = self.cfg.get("pinned_titles", [])
        if not saved_titles:
            return

        def enum_cb(hwnd, results):
            if win32gui.IsWindowVisible(hwnd):
                try:
                    title = win32gui.GetWindowText(hwnd)
                    if title in saved_titles:
                        results.append(hwnd)
                except Exception:
                    pass

        found = []
        win32gui.EnumWindows(enum_cb, found)
        for hwnd in found:
            self.pin(hwnd)

    def shutdown(self):
        self._stop.set()
        self.unpin_all()
        for h in self._hooks:
            try:
                windll.user32.UnhookWinEvent(h)
            except Exception:
                pass


# =============================================================================
# CAPTURA DE JANELA PELO CLIQUE
# =============================================================================

class WindowPicker:
    """Aguarda clique do usuário e retorna o HWND da janela clicada."""

    def __init__(self):
        self._result_hwnd: Optional[int] = None
        self._done = threading.Event()

        # Declarar argtypes corretos para WindowFromPoint (POINT por valor em x64)
        windll.user32.WindowFromPoint.restype  = wintypes.HWND
        windll.user32.WindowFromPoint.argtypes = [wintypes.POINT]

        windll.user32.GetAncestor.restype  = wintypes.HWND
        windll.user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]

    def pick(self) -> Optional[int]:
        self._result_hwnd = None
        self._done.clear()
        t = threading.Thread(target=self._capture_loop, daemon=True)
        t.start()
        self._done.wait(timeout=30)
        return self._result_hwnd

    def _capture_loop(self):
        try:
            hcursor  = windll.user32.LoadCursorW(0, ctypes.cast(IDC_CROSS, wintypes.LPCWSTR))
            old_cursor = windll.user32.SetCursor(hcursor)

            VK_LBUTTON = 0x01
            VK_ESCAPE  = 0x1B
            prev_state = windll.user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000

            while True:
                time.sleep(0.02)

                if windll.user32.GetAsyncKeyState(VK_ESCAPE) & 0x0001:
                    break

                cur_state = windll.user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000
                if cur_state and not prev_state:
                    pt = wintypes.POINT()
                    windll.user32.GetCursorPos(byref(pt))

                    # WindowFromPoint com argtypes correto (POINT por valor)
                    hwnd = windll.user32.WindowFromPoint(pt)
                    if hwnd:
                        GA_ROOT = 2
                        root = windll.user32.GetAncestor(hwnd, GA_ROOT)
                        hwnd = root if root else hwnd
                        try:
                            title = win32gui.GetWindowText(hwnd)
                        except Exception:
                            title = ""
                        if title and hwnd:
                            self._result_hwnd = hwnd
                    break

                prev_state = cur_state

        except Exception:
            pass
        finally:
            try:
                windll.user32.SetCursor(old_cursor)
            except Exception:
                pass
            self._done.set()


# =============================================================================
# BANDEJA DO SISTEMA
# =============================================================================

class TrayApp:
    """Ícone na bandeja + menu contextual."""

    def __init__(self):
        self.pin_manager = PinManager()
        self.picker      = WindowPicker()
        self._tray: Optional[pystray.Icon] = None
        self._picking    = False

    # ── Setup callback – roda NA thread do message loop do pystray ─────────

    def _on_tray_setup(self, icon):
        """
        Chamado pelo pystray assim que a janela oculta e o message loop estão prontos.
        É AQUI que os WinEventHooks devem ser instalados, pois agora o loop de
        mensagens está ativo na thread correta (main thread no Windows).
        """
        icon.visible = True
        self.pin_manager.install_hooks()

    # ── Execução ───────────────────────────────────────────────────────────

    def run(self):
        """Inicia o ícone na bandeja. Bloqueia até sair."""
        icon_img = make_tray_icon(64, active=self.pin_manager.is_protection_enabled())

        self._tray = pystray.Icon(
            "WinPins",
            icon_img,
            "WinPins – Clique direito para opções",
            menu=self._build_menu(),
        )
        # setup= garante que _on_tray_setup seja chamado com o loop já ativo
        self._tray.run(setup=self._on_tray_setup)

    # ── Menu ───────────────────────────────────────────────────────────────

    def _build_menu(self) -> Menu:
        protection_label = (
            "✓ Proteção Win+D: Ativada"
            if self.pin_manager.is_protection_enabled()
            else "✗ Proteção Win+D: Desativada"
        )

        pinned = self.pin_manager.get_pinned_list()
        if pinned:
            pinned_items = [item("── Janelas Fixadas ──", None, enabled=False)]
            for hwnd, title in pinned:
                short = (title[:40] + "…") if len(title) > 40 else title

                def make_unpin(h):
                    def action(icon, menu_item):
                        self.pin_manager.unpin(h)
                        self._refresh_menu()
                    return action

                pinned_items.append(item(f"📌 {short}", make_unpin(hwnd)))
        else:
            pinned_items = [item("(nenhuma janela fixada)", None, enabled=False)]

        return Menu(
            item("📌 Adicionar Pin",         self._on_add_pin),
            item("🗑️  Remover Todos os Pins", self._on_remove_all),
            Menu.SEPARATOR,
            item(protection_label,            self._on_toggle_protection),
            Menu.SEPARATOR,
            *pinned_items,
            Menu.SEPARATOR,
            item("❌ Sair",                   self._on_quit),
        )

    def _refresh_menu(self):
        if self._tray:
            self._tray.menu = self._build_menu()
            self._tray.icon = make_tray_icon(
                64, active=self.pin_manager.is_protection_enabled())

    def _on_add_pin(self, icon, menu_item):
        if self._picking:
            return
        self._picking = True

        def do_pick():
            try:
                hwnd = self.picker.pick()
                if hwnd and self.pin_manager.pin(hwnd):
                    self._refresh_menu()
            except Exception:
                pass
            finally:
                self._picking = False

        threading.Thread(target=do_pick, daemon=True).start()

    def _on_remove_all(self, icon, menu_item):
        self.pin_manager.unpin_all()
        self._refresh_menu()

    def _on_toggle_protection(self, icon, menu_item):
        self.pin_manager.set_protection(not self.pin_manager.is_protection_enabled())
        self._refresh_menu()

    def _on_quit(self, icon, menu_item):
        self.pin_manager.shutdown()
        icon.stop()


# =============================================================================
# PREVENÇÃO DE MÚLTIPLAS INSTÂNCIAS
# =============================================================================

def ensure_single_instance() -> wintypes.HANDLE:
    MUTEX_NAME    = "WinPins_SingleInstance_Mutex_7f3a9b"
    ERROR_ALREADY = 183
    h = windll.kernel32.CreateMutexW(None, True, MUTEX_NAME)
    if windll.kernel32.GetLastError() == ERROR_ALREADY:
        windll.user32.MessageBoxW(
            0,
            "WinPins já está em execução.\nVerifique a bandeja do sistema (ícones ocultos).",
            "WinPins",
            0x40)
        sys.exit(0)
    return h


# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    # ── Modo especial: exportar ícone para uso com PyInstaller ────────────
    if "--export-icon" in sys.argv:
        out = "winpins_icon.ico"
        save_icon_file(out)
        windll.user32.MessageBoxW(
            0, f"Ícone salvo em:\n{os.path.abspath(out)}", "WinPins", 0x40)
        return

    # ── Garantir única instância ──────────────────────────────────────────
    _mutex = ensure_single_instance()

    # ── Pré-gerar o .ico em APPDATA (usado como ícone do processo) ────────
    try:
        get_or_create_icon_path()
    except Exception:
        pass

    # ── Iniciar aplicação ─────────────────────────────────────────────────
    app = TrayApp()
    try:
        app.run()
    except Exception:
        # Com --windowed não há console; exibe erro em MessageBox e salva log
        err_text = traceback.format_exc()
        windll.user32.MessageBoxW(0, err_text[:1800], "WinPins – Erro Fatal", 0x10)

        log_path = os.path.join(
            os.environ.get("APPDATA", "."), "WinPins", "error.log")
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n{err_text}\n")
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()