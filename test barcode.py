import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk


# ============================================================
# WINDOWS RAW INPUT CONSTANTS
# ============================================================

WM_INPUT = 0x00FF
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104

RID_INPUT = 0x10000003
RIDI_DEVICENAME = 0x20000007

RIM_TYPEKEYBOARD = 1

VK_RETURN = 0x0D
VK_OEM_MINUS = 0xBD
VK_OEM_PERIOD = 0xBE
VK_OEM_2 = 0xBF       # /
VK_OEM_5 = 0xDC       # \
VK_OEM_1 = 0xBA       # ;
VK_OEM_COMMA = 0xBC


# ============================================================
# WINDOWS STRUCTURES
# ============================================================

class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [
        ("MakeCode", wintypes.USHORT),
        ("Flags", wintypes.USHORT),
        ("Reserved", wintypes.USHORT),
        ("VKey", wintypes.USHORT),
        ("Message", wintypes.UINT),
        ("ExtraInformation", wintypes.ULONG),
    ]


class RAWINPUT_UNION(ctypes.Union):
    _fields_ = [
        ("keyboard", RAWKEYBOARD),
    ]


class RAWINPUT(ctypes.Structure):
    _fields_ = [
        ("header", RAWINPUTHEADER),
        ("data", RAWINPUT_UNION),
    ]


user32 = ctypes.windll.user32


# ============================================================
# UI
# ============================================================

root = tk.Tk()
root.title("Barcode Scanner Test")
root.geometry("650x220")

barcode_var = tk.StringVar()
status_var = tk.StringVar(value="Click 'Learn scanner', then scan one barcode.")

ttk.Label(root, text="Barcode:").pack(pady=(20, 5))

barcode_entry = ttk.Entry(
    root,
    textvariable=barcode_var,
    state="readonly",
    font=("Segoe UI", 16),
    width=40,
)
barcode_entry.pack()

ttk.Label(
    root,
    textvariable=status_var,
    wraplength=600
).pack(pady=15)


# ============================================================
# SCANNER STATE
# ============================================================

scanner_device = None
scanner_buffer = ""
learning = False


def learn_scanner():
    global learning, scanner_device, scanner_buffer

    learning = True
    scanner_device = None
    scanner_buffer = ""

    status_var.set("Scan a barcode now...")


ttk.Button(
    root,
    text="Learn scanner",
    command=learn_scanner
).pack()


# ============================================================
# DEVICE NAME
# ============================================================

def get_device_name(device):
    size = wintypes.UINT(0)

    user32.GetRawInputDeviceInfoW(
        device,
        RIDI_DEVICENAME,
        None,
        ctypes.byref(size)
    )

    buffer = ctypes.create_unicode_buffer(size.value)

    user32.GetRawInputDeviceInfoW(
        device,
        RIDI_DEVICENAME,
        buffer,
        ctypes.byref(size)
    )

    return buffer.value


# ============================================================
# VERY SIMPLE VIRTUAL-KEY → CHARACTER
# Good enough for typical SKU / barcode strings.
# ============================================================

def key_to_char(vk):

    if 0x30 <= vk <= 0x39:
        return chr(vk)

    if 0x41 <= vk <= 0x5A:
        return chr(vk)

    mapping = {
        VK_OEM_MINUS: "-",
        VK_OEM_PERIOD: ".",
        VK_OEM_2: "/",
        VK_OEM_5: "\\",
        VK_OEM_1: ";",
        VK_OEM_COMMA: ",",
    }

    return mapping.get(vk, "")


# ============================================================
# RAW INPUT HANDLER
# ============================================================

def handle_raw_input(lparam):
    global scanner_device, scanner_buffer, learning

    size = wintypes.UINT(0)

    user32.GetRawInputData(
        lparam,
        RID_INPUT,
        None,
        ctypes.byref(size),
        ctypes.sizeof(RAWINPUTHEADER),
    )

    buffer = ctypes.create_string_buffer(size.value)

    user32.GetRawInputData(
        lparam,
        RID_INPUT,
        buffer,
        ctypes.byref(size),
        ctypes.sizeof(RAWINPUTHEADER),
    )

    raw = ctypes.cast(
        buffer,
        ctypes.POINTER(RAWINPUT)
    ).contents

    if raw.header.dwType != RIM_TYPEKEYBOARD:
        return

    keyboard = raw.data.keyboard

    # Ignore key releases
    if keyboard.Message not in (WM_KEYDOWN, WM_SYSKEYDOWN):
        return

    device = raw.header.hDevice

    # --------------------------------------------------------
    # First scan teaches us which physical device is scanner
    # --------------------------------------------------------

    if learning:
        scanner_device = device
        learning = False

        name = get_device_name(device)

        status_var.set(
            "Scanner learned:\n" + name
        )

    # Ignore normal keyboard
    if device != scanner_device:
        return

    vk = keyboard.VKey

    # Scanner sends Enter at end
    if vk == VK_RETURN:

        if scanner_buffer:
            barcode_var.set(scanner_buffer)
            print("SCANNED:", scanner_buffer)

        scanner_buffer = ""
        return

    char = key_to_char(vk)

    if char:
        scanner_buffer += char


# ============================================================
# HOOK WM_INPUT INTO TK WINDOW
# ============================================================

root.update_idletasks()
hwnd = root.winfo_id()

GWLP_WNDPROC = -4

# Windows pointer-sized result type
LRESULT = ctypes.c_ssize_t

WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM
)

# ------------------------------------------------------------
# VERY IMPORTANT:
# Explicit 64-bit ctypes signatures
# ------------------------------------------------------------

user32.GetWindowLongPtrW.argtypes = [
    wintypes.HWND,
    ctypes.c_int
]
user32.GetWindowLongPtrW.restype = ctypes.c_void_p


user32.SetWindowLongPtrW.argtypes = [
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_void_p
]
user32.SetWindowLongPtrW.restype = ctypes.c_void_p


user32.CallWindowProcW.argtypes = [
    ctypes.c_void_p,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM
]
user32.CallWindowProcW.restype = LRESULT


# Get Tk's original window procedure
old_wndproc = user32.GetWindowLongPtrW(
    hwnd,
    GWLP_WNDPROC
)

if not old_wndproc:
    raise ctypes.WinError()


# ------------------------------------------------------------
# OUR WINDOW PROCEDURE
# ------------------------------------------------------------

def wndproc(hwnd, msg, wparam, lparam):

    if msg == WM_INPUT:
        try:
            handle_raw_input(lparam)
        except Exception as e:
            print("RAW INPUT ERROR:", e)

    return user32.CallWindowProcW(
        old_wndproc,
        hwnd,
        msg,
        wparam,
        lparam
    )


# IMPORTANT:
# Keep this object alive for the whole application lifetime.
new_wndproc = WNDPROC(wndproc)


new_wndproc_ptr = ctypes.cast(
    new_wndproc,
    ctypes.c_void_p
)


result = user32.SetWindowLongPtrW(
    hwnd,
    GWLP_WNDPROC,
    new_wndproc_ptr
)


# ============================================================
# REGISTER FOR RAW KEYBOARD INPUT
# ============================================================

rid = RAWINPUTDEVICE()

rid.usUsagePage = 0x01   # Generic Desktop
rid.usUsage = 0x06       # Keyboard
rid.dwFlags = 0
rid.hwndTarget = hwnd

if not user32.RegisterRawInputDevices(
    ctypes.byref(rid),
    1,
    ctypes.sizeof(rid)
):
    raise ctypes.WinError()


root.mainloop()