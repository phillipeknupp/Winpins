# =============================================================================
# WinPins - Clone leve do DeskPins para Windows
# Um único arquivo Python autocontido
# =============================================================================
# Dependências: pip install pywin32 pystray Pillow
#
# Build EXE:
#   pyinstaller --onefile --windowed --icon=NONE winpins.py
#   (ou com ícone gerado: pyinstaller --onefile --windowed winpins.py)
# =============================================================================

import sys
import os
import json
import time
import threading
import ctypes
import ctypes.wintypes
import io
import math
import traceback
from ctypes import windll, wintypes, byref, c_int, c_long, c_ulong, POINTER
from typing import Optional, Dict, Set

# ── Dependências externas ─────────────────────────────────────────────────────
try:
    import win32gui
    import win32con
    import win32api
    import win32process
    import pywintypes
except ImportError:
    print("Instale pywin32: pip install pywin32")
    sys.exit(1)

try:
    import pystray
    from pystray import MenuItem as item, Menu
except ImportError:
    print("Instale pystray: pip install pystray")
    sys.exit(1)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Instale Pillow: pip install Pillow")
    sys.exit(1)

# =============================================================================
# CONSTANTES WINAPI
# =============================================================================

# Posicionamento de janelas
HWND_TOPMOST    = -1
HWND_NOTOPMOST  = -2
SWP_NOMOVE      = 0x0002
SWP_NOSIZE      = 0x0001
SWP_NOACTIVATE  = 0x0010
SWP_SHOWWINDOW  = 0x0040

# ShowWindow comandos
SW_RESTORE   = 9
SW_SHOW      = 5
SW_SHOWNA    = 8
SW_MINIMIZE  = 6

# Mensagens de janela
WM_SYSCOMMAND  = 0x0112
SC_MINIMIZE    = 0xF020
WM_SIZE        = 0x0005
SIZE_MINIMIZED = 1
WM_MOVE        = 0x0003
WM_DESTROY     = 0x0002
WM_CLOSE       = 0x0010
WM_NCDESTROY   = 0x0082

# Estilos de janela
WS_EX_LAYERED       = 0x00080000
WS_EX_TRANSPARENT   = 0x00000020
WS_EX_TOPMOST       = 0x00000008
WS_EX_TOOLWINDOW    = 0x00000080
WS_EX_NOACTIVATE    = 0x08000000
WS_POPUP            = 0x80000000
GWL_EXSTYLE         = -20
GWL_STYLE           = -16

# Layered window attributes
LWA_COLORKEY = 0x00000001
LWA_ALPHA    = 0x00000002

# SetWinEventHook eventos
EVENT_SYSTEM_MINIMIZESTART = 0x0016
EVENT_SYSTEM_MINIMIZEEND   = 0x0017
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
EVENT_OBJECT_DESTROY        = 0x8001
EVENT_OBJECT_SHOW           = 0x8002
EVENT_SYSTEM_MOVESIZESTART  = 0x000A
EVENT_SYSTEM_MOVESIZEEND    = 0x000B
WINEVENT_OUTOFCONTEXT      = 0x0000
WINEVENT_SKIPOWNPROCESS    = 0x0002

# GetSystemMetrics
SM_CXSCREEN = 0
SM_CYSCREEN = 1

# Cursor
IDC_ARROW   = 32512
IDC_CROSS   = 32515
IDC_WAIT    = 32514

# Classe de hook
HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
WinEventProc = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,  # hWinEventHook
    wintypes.DWORD,   # event
    wintypes.HWND,    # hwnd
    wintypes.LONG,    # idObject
    wintypes.LONG,    # idChild
    wintypes.DWORD,   # dwEventThread
    wintypes.DWORD,   # dwmsEventTime
)

# =============================================================================
# ARQUIVO DE CONFIGURAÇÃO / PERSISTÊNCIA
# =============================================================================

CONFIG_PATH = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "WinPins", "config.json")

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
# GERAÇÃO DE ÍCONES EM MEMÓRIA (sem assets externos)
# =============================================================================

def make_tray_icon(size=64, active=True) -> Image.Image:
    """
    Desenha ícone de bandeja: fundo azul-escuro com um alfinete (pin) estilizado.
    Se active=False, desenha em cinza (indicando que proteção está desligada).
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    bg_color = (30, 60, 120, 255) if active else (70, 70, 70, 255)
    pin_color = (220, 60, 60, 255) if active else (150, 150, 150, 255)

    # Fundo arredondado
    margin = 4
    d.ellipse([margin, margin, size - margin, size - margin], fill=bg_color)

    # Corpo do pin (cabeça redonda + haste)
    cx = size // 2
    # Cabeça
    head_r = size // 5
    head_cy = size // 3
    d.ellipse([cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r], fill=pin_color)

    # Brilho na cabeça
    d.ellipse([cx - head_r + 3, head_cy - head_r + 3, cx - 2, head_cy - 2],
              fill=(255, 200, 200, 180))

    # Haste
    haste_top = head_cy + head_r - 2
    haste_bot = size - margin - 6
    haste_w   = max(2, size // 14)
    d.rectangle([cx - haste_w, haste_top, cx + haste_w, haste_bot], fill=pin_color)

    # Ponta da haste (triângulo)
    d.polygon([
        (cx - haste_w - 1, haste_bot),
        (cx + haste_w + 1, haste_bot),
        (cx, haste_bot + 6)
    ], fill=pin_color)

    return img


def make_pin_overlay_image(w=20, h=20) -> Image.Image:
    """
    Pequena imagem para o overlay visual do pin sobre a janela.
    Alfinete vermelho com sombra leve.
    """
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    pin_color = (210, 40, 40, 240)
    cx = w // 2

    # Sombra
    d.ellipse([3, 3, w - 1, h // 2 + 2], fill=(0, 0, 0, 80))

    # Cabeça
    r = w // 3
    head_cy = h // 3
    d.ellipse([cx - r, head_cy - r, cx + r, head_cy + r], fill=pin_color)
    d.ellipse([cx - r + 2, head_cy - r + 2, cx - 1, head_cy - 1],
              fill=(255, 160, 160, 200))

    # Haste
    d.rectangle([cx - 1, head_cy + r - 1, cx + 1, h - 3], fill=pin_color)
    d.polygon([(cx - 2, h - 3), (cx + 2, h - 3), (cx, h)], fill=pin_color)

    return img


def pil_to_hicon(img: Image.Image):
    """Converte PIL Image para HICON do Windows (para cursor/ícone)."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# =============================================================================
# OVERLAY VISUAL (janelinha sem borda sobre a barra de título)
# =============================================================================

class PinOverlay:
    """
    Cria uma pequena janela transparente com o ícone de pin
    posicionada no canto superior-esquerdo da janela-alvo.
    Acompanha movimento, redimensionamento e múltiplos monitores.
    """

    OVERLAY_W = 20
    OVERLAY_H = 20
    OFFSET_X  = 8   # deslocamento em relação à barra de título
    OFFSET_Y  = 4

    def __init__(self, target_hwnd: int):
        self.target_hwnd = target_hwnd
        self.hwnd: Optional[int] = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        """
        Cria a janela overlay e roda a message pump na mesma thread.
        Posição é atualizada a cada 50ms via PeekMessage loop.
        IMPORTANTE: janela Win32 deve ser criada e ter mensagens processadas
        na mesma thread — nunca chamar DestroyWindow de outra thread.
        """
        try:
            self._create_window()
        except Exception:
            self._stop.set()
            return

        _WM_QUIT = 0x0012
        msg = wintypes.MSG()
        while not self._stop.is_set():
            # PeekMessage não bloqueante — processa todas as mensagens pendentes
            while windll.user32.PeekMessageW(byref(msg), 0, 0, 0, 1):  # PM_REMOVE=1
                if msg.message == _WM_QUIT:
                    return
                windll.user32.TranslateMessage(byref(msg))
                windll.user32.DispatchMessageW(byref(msg))
            # Reposicionar overlay acompanhando a janela-alvo
            self._reposition()
            self._stop.wait(0.05)

        # Destruir janela na mesma thread que a criou
        if self.hwnd:
            try:
                windll.user32.DestroyWindow(self.hwnd)
            except Exception:
                pass
            self.hwnd = None

    def _create_window(self):
        """Registra classe e cria janela overlay transparente via WinAPI puro."""
        hinstance = windll.kernel32.GetModuleHandleW(None)

        # Nome único da classe para evitar conflitos entre instâncias
        class_name = f"WinPinsOverlay_{self.target_hwnd}"

        # ── Tipos corretos para WndProc em Windows 64-bit ────────────────────
        # wintypes.WPARAM / LPARAM são aliases de c_ulong (32 bits) no CPython
        # padrão, mesmo em sistemas 64-bit. Quando o Windows envia mensagens
        # como WM_NCCREATE ou WM_GETMINMAXINFO com ponteiros como LPARAM, o
        # valor ultrapassa 2^32 e ctypes lança OverflowError no callback.
        # Correção: usar c_size_t (UINT_PTR) e c_ssize_t (LONG_PTR) que têm
        # largura nativa da plataforma (64 bits em x64, 32 em x86).
        _WPARAM  = ctypes.c_size_t    # UINT_PTR
        _LPARAM  = ctypes.c_ssize_t   # LONG_PTR
        _LRESULT = ctypes.c_ssize_t   # LRESULT

        WndProcType = ctypes.WINFUNCTYPE(
            _LRESULT,
            wintypes.HWND,
            wintypes.UINT,
            _WPARAM,
            _LPARAM,
        )

        # Também fixar argtypes/restype da própria API para evitar conversão errada
        _DefWindowProc = windll.user32.DefWindowProcW
        _DefWindowProc.restype  = _LRESULT
        _DefWindowProc.argtypes = [wintypes.HWND, wintypes.UINT, _WPARAM, _LPARAM]

        _WM_DESTROY = 0x0002
        _WM_PAINT   = 0x000F

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == _WM_PAINT:
                ps = ctypes.create_string_buffer(72)  # PAINTSTRUCT (64-bit safe)
                hdc = windll.user32.BeginPaint(hwnd, ps)
                self._draw_pin_hdc(hdc)
                windll.user32.EndPaint(hwnd, ps)
                return 0
            if msg == _WM_DESTROY:
                return 0
            return _DefWindowProc(hwnd, msg, wparam, lparam)

        # Manter referência no self para evitar garbage collection do callback
        self._wnd_proc_cb = WndProcType(wnd_proc)

        # WNDCLASSEX com o WndProcType que tem a assinatura correta
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
        wc.style         = 0
        wc.lpfnWndProc   = self._wnd_proc_cb
        wc.hInstance     = hinstance
        wc.hbrBackground = 0         # preto será transparente via color key
        wc.lpszClassName = class_name

        windll.user32.RegisterClassExW(byref(wc))

        x, y = self._get_position()

        # Estilos combinados do overlay:
        #   WS_EX_LAYERED    → habilita color-key transparency
        #   WS_EX_TRANSPARENT→ mouse clicks passam através
        #   WS_EX_TOPMOST    → sempre acima
        #   WS_EX_TOOLWINDOW → oculto da taskbar
        #   WS_EX_NOACTIVATE → não rouba foco
        ex_style = (WS_EX_LAYERED | WS_EX_TRANSPARENT |
                    WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)

        hwnd = windll.user32.CreateWindowExW(
            ex_style,
            class_name,
            "WinPinsOverlay",
            WS_POPUP,
            x, y, self.OVERLAY_W, self.OVERLAY_H,
            0, 0, hinstance, 0
        )

        if not hwnd:
            raise RuntimeError(f"CreateWindowExW falhou (erro {windll.kernel32.GetLastError()})")

        self.hwnd = hwnd

        # Preto (0x000000) como cor transparente; alpha ignorado com LWA_COLORKEY
        windll.user32.SetLayeredWindowAttributes(hwnd, 0x00000000, 255, LWA_COLORKEY)

        windll.user32.ShowWindow(hwnd, SW_SHOWNA)
        windll.user32.UpdateWindow(hwnd)

    def _draw_pin_hdc(self, hdc):
        """
        Pinta o ícone do pin em um HDC já aberto (chamado tanto em WM_PAINT
        quanto diretamente após criar a janela).
        Fundo preto = transparente via color key.
        """
        try:
            W, H = self.OVERLAY_W, self.OVERLAY_H
            # Preenche fundo preto (cor transparente)
            black_brush = windll.gdi32.CreateSolidBrush(0x00000000)
            rc = wintypes.RECT(0, 0, W, H)
            windll.user32.FillRect(hdc, byref(rc), black_brush)
            windll.gdi32.DeleteObject(black_brush)

            cx  = W // 2
            r   = W // 3
            hcy = H // 3

            # BGR para vermelho: 0x002828D2
            red_brush = windll.gdi32.CreateSolidBrush(0x002828D2)
            red_pen   = windll.gdi32.CreatePen(0, 1, 0x002828D2)
            old_brush = windll.gdi32.SelectObject(hdc, red_brush)
            old_pen   = windll.gdi32.SelectObject(hdc, red_pen)

            # Cabeça do pin
            windll.gdi32.Ellipse(hdc, cx - r, hcy - r, cx + r, hcy + r)
            # Haste
            windll.gdi32.Rectangle(hdc, cx - 1, hcy + r - 1, cx + 2, H - 2)

            windll.gdi32.SelectObject(hdc, old_brush)
            windll.gdi32.SelectObject(hdc, old_pen)
            windll.gdi32.DeleteObject(red_brush)
            windll.gdi32.DeleteObject(red_pen)
        except Exception:
            pass

    def _get_position(self):
        """Calcula posição do overlay com base na janela-alvo."""
        try:
            rect = win32gui.GetWindowRect(self.target_hwnd)
            x = rect[0] + self.OFFSET_X
            y = rect[1] + self.OFFSET_Y
            return x, y
        except Exception:
            return 0, 0

    def _reposition(self):
        """
        Reposiciona o overlay acompanhando a janela-alvo.
        Chamado a cada iteração do loop de mensagens (a cada ~50ms).
        """
        if not self.hwnd:
            return
        try:
            if not win32gui.IsWindow(self.target_hwnd):
                self._stop.set()
                return
            placement = win32gui.GetWindowPlacement(self.target_hwnd)
            # placement[1] == showCmd: 2 = minimizado
            if placement[1] == 2:
                windll.user32.ShowWindow(self.hwnd, 0)  # SW_HIDE
            else:
                x, y = self._get_position()
                windll.user32.SetWindowPos(
                    self.hwnd, HWND_TOPMOST,
                    x, y, self.OVERLAY_W, self.OVERLAY_H,
                    SWP_NOACTIVATE | SWP_SHOWWINDOW
                )
        except Exception:
            pass

    def destroy(self):
        """
        Sinaliza parada do loop — a thread do overlay destruirá a janela
        na própria thread criadora (requisito do Win32).
        """
        self._stop.set()
        # Não chamar DestroyWindow aqui — seria cross-thread


# =============================================================================
# GERENCIADOR DE PINS
# =============================================================================

class PinManager:
    """
    Gerencia o conjunto de janelas fixadas.
    Responsabilidades:
      - Aplicar HWND_TOPMOST
      - Registrar WinEventHook para detectar minimização
      - Restaurar janelas quando minimizadas (proteção Win+D)
      - Manter overlays visuais
      - Persistência (JSON)
      - Limpeza automática de janelas fechadas
    """

    def __init__(self):
        self.cfg = load_config()
        # hwnd -> {"title": str, "overlay": PinOverlay}
        self.pinned: Dict[int, dict] = {}
        self._lock = threading.Lock()
        self._hooks = []          # handles de WinEventHook
        self._stop = threading.Event()

        # Thread que monitora janelas minimizadas
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

        # Instalar hooks de eventos globais
        self._install_hooks()

        # Restaurar pins de sessão anterior
        self._restore_persisted_pins()

    # ── Hooks WinAPI ──────────────────────────────────────────────────────────

    def _install_hooks(self):
        """
        Instala WinEventHooks para:
          EVENT_SYSTEM_MINIMIZESTART — detectar minimização de qualquer janela
          EVENT_OBJECT_LOCATIONCHANGE — detectar mover/redimensionar (para overlay)
          EVENT_OBJECT_DESTROY — detectar fechamento de janelas pinadas
        """
        # Callback precisa ser armazenado para evitar garbage collection
        self._hook_cb = WinEventProc(self._win_event_proc)

        def install(event_min, event_max):
            h = windll.user32.SetWinEventHook(
                event_min, event_max,
                0,                        # hmodWinEventProc (0 = out-of-process)
                self._hook_cb,
                0, 0,                     # pid/tid = 0 → todos os processos
                WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS
            )
            if h:
                self._hooks.append(h)

        install(EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZESTART)
        install(EVENT_OBJECT_DESTROY, EVENT_OBJECT_DESTROY)

    def _win_event_proc(self, hHook, event, hwnd, idObject, idChild, dwThread, dwTime):
        """
        Callback chamado pelo Windows para eventos de janela.
        Roda na thread que fez SetWinEventHook (thread principal da message pump).
        """
        try:
            if event == EVENT_SYSTEM_MINIMIZESTART:
                # Uma janela foi minimizada — verificar se está pinada
                if hwnd and self._is_pinned(hwnd):
                    if self.cfg.get("protection_enabled", True):
                        # Agendar restore imediato em thread separada
                        # para não bloquear o hook
                        threading.Thread(
                            target=self._restore_window,
                            args=(hwnd,),
                            daemon=True
                        ).start()

            elif event == EVENT_OBJECT_DESTROY:
                # Janela destruída — limpar pin se existir
                if hwnd and self._is_pinned(hwnd):
                    threading.Thread(
                        target=self._cleanup_pin,
                        args=(hwnd,),
                        daemon=True
                    ).start()
        except Exception:
            pass

    def _restore_window(self, hwnd: int):
        """
        Restaura uma janela minimizada.
        Usa pequeno delay para deixar o Windows completar a animação de minimização,
        depois restaura — minimiza o "flicker" visual.
        """
        try:
            time.sleep(0.05)   # aguarda animação de minimização
            if not win32gui.IsWindow(hwnd):
                return
            # Verifica se ainda está pinada (pode ter sido removida)
            if not self._is_pinned(hwnd):
                return
            # Restaura a janela
            win32gui.ShowWindow(hwnd, SW_RESTORE)
            # Reaplica topmost caso tenha sido perdido
            windll.user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            )
        except Exception:
            pass

    def _cleanup_pin(self, hwnd: int):
        """Remove pin de janela fechada."""
        time.sleep(0.1)
        self.unpin(hwnd, silent=True)

    def _is_pinned(self, hwnd: int) -> bool:
        with self._lock:
            return hwnd in self.pinned

    # ── Monitor de integridade ────────────────────────────────────────────────

    def _monitor_loop(self):
        """
        Loop a cada 500ms:
          - Remove pins de janelas que não existem mais
          - Reaplica TOPMOST em janelas pinadas (algumas apps removem o flag)
          - Detecta minimizações que o hook pode ter perdido (Win+D em alguns cenários)
        """
        while not self._stop.is_set():
            try:
                with self._lock:
                    hwnds = list(self.pinned.keys())

                for hwnd in hwnds:
                    try:
                        if not win32gui.IsWindow(hwnd):
                            self.unpin(hwnd, silent=True)
                            continue

                        # Reaplica topmost
                        windll.user32.SetWindowPos(
                            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
                        )

                        # Proteção extra: detectar minimização
                        if self.cfg.get("protection_enabled", True):
                            placement = win32gui.GetWindowPlacement(hwnd)
                            if placement[1] == 2:   # SW_SHOWMINIMIZED
                                self._restore_window(hwnd)

                    except Exception:
                        pass
            except Exception:
                pass

            self._stop.wait(0.5)

    # ── API pública ───────────────────────────────────────────────────────────

    def pin(self, hwnd: int) -> bool:
        """Fixa uma janela: aplica topmost e cria overlay."""
        if not win32gui.IsWindow(hwnd):
            return False

        with self._lock:
            if hwnd in self.pinned:
                return False  # já pinada

        try:
            title = win32gui.GetWindowText(hwnd)
        except Exception:
            title = "(sem título)"

        # Aplicar HWND_TOPMOST
        windll.user32.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
        )

        # Criar overlay visual
        overlay = PinOverlay(hwnd)

        with self._lock:
            self.pinned[hwnd] = {
                "title":   title,
                "overlay": overlay,
            }

        self._persist()
        return True

    def unpin(self, hwnd: int, silent=False) -> bool:
        """Remove o pin de uma janela."""
        with self._lock:
            entry = self.pinned.pop(hwnd, None)

        if entry is None:
            return False

        # Remover topmost
        try:
            if win32gui.IsWindow(hwnd):
                windll.user32.SetWindowPos(
                    hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
                )
        except Exception:
            pass

        # Destruir overlay
        try:
            entry["overlay"].destroy()
        except Exception:
            pass

        if not silent:
            self._persist()
        return True

    def unpin_all(self):
        """Remove todos os pins."""
        with self._lock:
            hwnds = list(self.pinned.keys())
        for hwnd in hwnds:
            self.unpin(hwnd)

    def get_pinned_list(self) -> list:
        """Retorna lista de (hwnd, título) das janelas pinadas."""
        with self._lock:
            return [(hwnd, d["title"]) for hwnd, d in self.pinned.items()]

    def set_protection(self, enabled: bool):
        self.cfg["protection_enabled"] = enabled
        save_config(self.cfg)

    def is_protection_enabled(self) -> bool:
        return self.cfg.get("protection_enabled", True)

    # ── Persistência ─────────────────────────────────────────────────────────

    def _persist(self):
        """Salva títulos das janelas pinadas para tentar restaurar na próxima sessão."""
        with self._lock:
            titles = [d["title"] for d in self.pinned.values() if d["title"]]
        self.cfg["pinned_titles"] = titles
        save_config(self.cfg)

    def _restore_persisted_pins(self):
        """
        Ao iniciar, tenta encontrar janelas com os mesmos títulos da sessão anterior
        e as repina automaticamente.
        """
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

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def shutdown(self):
        """Para todos os threads e remove hooks."""
        self._stop.set()
        self.unpin_all()
        for h in self._hooks:
            try:
                windll.user32.UnhookWinEvent(h)
            except Exception:
                pass


# =============================================================================
# CAPTURA DE JANELA PELO CLIQUE (modo "Adicionar Pin")
# =============================================================================

class WindowPicker:
    """
    Ao entrar em modo de seleção:
      1. Captura o mouse (SetCapture)
      2. Troca o cursor para uma cruz/alfinete personalizado
      3. Aguarda clique do usuário
      4. Identifica a janela sob o cursor (WindowFromPoint / RealChildWindowFromPoint)
      5. Sobe para o ancestral de nível top-level
      6. Retorna o HWND
    """

    def __init__(self):
        self._result_hwnd: Optional[int] = None
        self._done = threading.Event()

    def pick(self) -> Optional[int]:
        """Inicia captura de janela. Bloqueia até o usuário clicar. Retorna HWND ou None."""
        self._result_hwnd = None
        self._done.clear()

        t = threading.Thread(target=self._capture_loop, daemon=True)
        t.start()
        self._done.wait(timeout=30)  # timeout de 30s
        return self._result_hwnd

    def _capture_loop(self):
        """
        Loop de captura: aguarda clique esquerdo e identifica a janela.
        Usa uma janela invisible que captura mouse globalmente.
        """
        try:
            # Mudar cursor do sistema para cruz
            hcursor = windll.user32.LoadCursorW(0, ctypes.cast(IDC_CROSS, wintypes.LPCWSTR))
            old_cursor = windll.user32.SetCursor(hcursor)

            # Pequena instrução visual via MessageBox assíncrono
            # (não bloqueamos o loop principal)
            import ctypes as _ct
            MB_ICONINFORMATION = 0x40
            MB_OK = 0
            # Mostrar balão de dica via tray (sem MessageBox para não bloquear)

            # Polling com GetAsyncKeyState para detectar clique esquerdo
            VK_LBUTTON  = 0x01
            VK_ESCAPE   = 0x1B
            prev_state  = windll.user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000

            while True:
                time.sleep(0.02)

                # Escape cancela
                if windll.user32.GetAsyncKeyState(VK_ESCAPE) & 0x0001:
                    break

                cur_state = windll.user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000

                # Detecta borda de descida (botão pressionado agora, antes não)
                if cur_state and not prev_state:
                    # Obter posição do cursor
                    pt = wintypes.POINT()
                    windll.user32.GetCursorPos(byref(pt))

                    # Identificar janela sob o cursor
                    hwnd = windll.user32.WindowFromPoint(pt)

                    if hwnd:
                        # Subir para a janela top-level (ancestral sem pai)
                        hwnd = self._get_top_level(hwnd)

                        # Ignorar a própria janela do picker e a tray
                        title = ""
                        try:
                            title = win32gui.GetWindowText(hwnd)
                        except Exception:
                            pass

                        if title and hwnd:
                            self._result_hwnd = hwnd
                    break

                prev_state = cur_state

        except Exception:
            pass
        finally:
            # Restaurar cursor
            try:
                windll.user32.SetCursor(old_cursor)
            except Exception:
                pass
            self._done.set()

    def _get_top_level(self, hwnd: int) -> int:
        """Sobe a hierarquia de janelas até encontrar a janela top-level."""
        GA_ROOT = 2
        root = windll.user32.GetAncestor(hwnd, GA_ROOT)
        return root if root else hwnd


# =============================================================================
# BANDEJA DO SISTEMA (pystray)
# =============================================================================

class TrayApp:
    """
    Gerencia o ícone na bandeja do sistema usando pystray.
    Constrói menu contextual dinâmico e integra com PinManager.
    """

    def __init__(self):
        self.pin_manager = PinManager()
        self.picker      = WindowPicker()
        self._tray: Optional[pystray.Icon] = None
        self._picking    = False

    def run(self):
        """Inicia o ícone na bandeja. Bloqueia até sair."""
        icon_img = make_tray_icon(64, active=self.pin_manager.is_protection_enabled())

        self._tray = pystray.Icon(
            "WinPins",
            icon_img,
            "WinPins",
            menu=self._build_menu()
        )
        self._tray.run()

    def _build_menu(self) -> Menu:
        """Constrói o menu de contexto dinamicamente."""
        protection_label = (
            "✓ Proteção Win+D: Ativada"
            if self.pin_manager.is_protection_enabled()
            else "✗ Proteção Win+D: Desativada"
        )

        pinned = self.pin_manager.get_pinned_list()
        pinned_items = []
        if pinned:
            pinned_items.append(item("── Janelas Fixadas ──", None, enabled=False))
            for hwnd, title in pinned:
                short = (title[:40] + "…") if len(title) > 40 else title
                # Cria closure para capturar hwnd corretamente
                def make_unpin(h):
                    def unpin_action(icon, menu_item):
                        self.pin_manager.unpin(h)
                        self._refresh_menu()
                    return unpin_action
                pinned_items.append(item(f"📌 {short}", make_unpin(hwnd)))
        else:
            pinned_items.append(item("(nenhuma janela fixada)", None, enabled=False))

        return Menu(
            item("📌 Adicionar Pin",          self._on_add_pin),
            item("🗑️  Remover Todos os Pins",  self._on_remove_all),
            Menu.SEPARATOR,
            item(protection_label,             self._on_toggle_protection),
            Menu.SEPARATOR,
            *pinned_items,
            Menu.SEPARATOR,
            item("❌ Sair",                    self._on_quit),
        )

    def _refresh_menu(self):
        """Atualiza o menu e o ícone da bandeja."""
        if self._tray:
            self._tray.menu = self._build_menu()
            new_icon = make_tray_icon(64, active=self.pin_manager.is_protection_enabled())
            self._tray.icon = new_icon

    def _on_add_pin(self, icon, menu_item):
        """
        Inicia modo de seleção de janela.
        Roda em thread separada para não bloquear a mensagem pump do pystray.
        """
        if self._picking:
            return
        self._picking = True

        def do_pick():
            try:
                hwnd = self.picker.pick()
                if hwnd:
                    ok = self.pin_manager.pin(hwnd)
                    if ok:
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
        new_state = not self.pin_manager.is_protection_enabled()
        self.pin_manager.set_protection(new_state)
        self._refresh_menu()

    def _on_quit(self, icon, menu_item):
        self.pin_manager.shutdown()
        icon.stop()

    # ── Message pump para WinEventHooks ──────────────────────────────────────
    # WinEventHooks precisam de uma message loop na thread que os instalou.
    # Como pystray.run() cria sua própria loop, instalamos os hooks
    # e rodamos GetMessage em thread auxiliar.


# =============================================================================
# MESSAGE PUMP (necessária para WinEventHooks)
# =============================================================================

def run_message_pump():
    """
    WinEventHooks instalados com WINEVENT_OUTOFCONTEXT precisam que a thread
    que os instalou processe mensagens (GetMessage / DispatchMessage).
    Esta função roda esse loop.
    """
    msg = wintypes.MSG()
    while windll.user32.GetMessageW(byref(msg), 0, 0, 0) != 0:
        windll.user32.TranslateMessage(byref(msg))
        windll.user32.DispatchMessageW(byref(msg))


# =============================================================================
# PREVENÇÃO DE MÚLTIPLAS INSTÂNCIAS
# =============================================================================

def ensure_single_instance() -> Optional[wintypes.HANDLE]:
    """
    Usa mutex nomeado para garantir que só uma instância rode por vez.
    Retorna o handle do mutex (deve ser mantido vivo).
    """
    MUTEX_NAME = "WinPins_SingleInstance_Mutex_7f3a9b"
    h = windll.kernel32.CreateMutexW(None, True, MUTEX_NAME)
    last_err = windll.kernel32.GetLastError()
    ERROR_ALREADY_EXISTS = 183
    if last_err == ERROR_ALREADY_EXISTS:
        # Já está rodando
        windll.user32.MessageBoxW(
            0,
            "WinPins já está em execução.\nVerifique a bandeja do sistema.",
            "WinPins",
            0x40  # MB_ICONINFORMATION
        )
        sys.exit(0)
    return h


# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    # Garantir instância única
    _mutex = ensure_single_instance()

    # Iniciar pump de mensagens em thread separada
    # (necessário para que WinEventHooks recebam eventos)
    pump_thread = threading.Thread(target=run_message_pump, daemon=True)
    pump_thread.start()

    # Iniciar tray app (bloqueia até sair)
    app = TrayApp()
    try:
        app.run()
    except Exception as e:
        # Em caso de erro fatal, logar e sair limpo
        log_path = os.path.join(os.environ.get("APPDATA", "."), "WinPins", "error.log")
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n")
                traceback.print_exc(file=f)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()