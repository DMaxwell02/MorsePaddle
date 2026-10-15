import ctypes
import queue
import threading
import time
import uuid
from ctypes import wintypes
from dataclasses import dataclass
from typing import Self

from morse_paddle.raw_keyboard import RawInputError, RawKeyboardDevice, RawKeyEvent

BYTE = ctypes.c_uint8
WORD = USHORT = ctypes.c_uint16
DWORD = UINT = ULONG = ctypes.c_uint32
BOOL = LONG = ctypes.c_int32
HANDLE = HWND = HINSTANCE = ctypes.c_void_p
WPARAM = ctypes.c_size_t
LPARAM = LRESULT = ctypes.c_ssize_t

RIM_TYPEKEYBOARD = 1
RIDI_DEVICENAME = 0x20000007
RIDI_DEVICEINFO = 0x2000000B
RID_INPUT = 0x10000003
RIDEV_REMOVE = 0x00000001
RIDEV_INPUTSINK = 0x00000100
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_INPUT = 0x00FF
RIM_INPUT = 0
RI_KEY_BREAK = 0x01
RI_KEY_E0 = 0x02
RI_KEY_E1 = 0x04
UINT_ERROR = 0xFFFFFFFF
ERROR_INSUFFICIENT_BUFFER = 122
HWND_MESSAGE = ctypes.c_void_p(-3)


class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [("hDevice", HANDLE), ("dwType", DWORD)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", DWORD),
        ("dwSize", DWORD),
        ("hDevice", HANDLE),
        ("wParam", WPARAM),
    ]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [
        ("MakeCode", USHORT),
        ("Flags", USHORT),
        ("Reserved", USHORT),
        ("VKey", USHORT),
        ("Message", UINT),
        ("ExtraInformation", ULONG),
    ]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", USHORT),
        ("usUsage", USHORT),
        ("dwFlags", DWORD),
        ("hwndTarget", HWND),
    ]


class RID_DEVICE_INFO_MOUSE(ctypes.Structure):
    _fields_ = [
        ("dwId", DWORD),
        ("dwNumberOfButtons", DWORD),
        ("dwSampleRate", DWORD),
        ("fHasHorizontalWheel", BOOL),
    ]


class RID_DEVICE_INFO_KEYBOARD(ctypes.Structure):
    _fields_ = [
        ("dwType", DWORD),
        ("dwSubType", DWORD),
        ("dwKeyboardMode", DWORD),
        ("dwNumberOfFunctionKeys", DWORD),
        ("dwNumberOfIndicators", DWORD),
        ("dwNumberOfKeysTotal", DWORD),
    ]


class RID_DEVICE_INFO_HID(ctypes.Structure):
    _fields_ = [
        ("dwVendorId", DWORD),
        ("dwProductId", DWORD),
        ("dwVersionNumber", DWORD),
        ("usUsagePage", USHORT),
        ("usUsage", USHORT),
    ]


class RID_DEVICE_INFO_UNION(ctypes.Union):
    _fields_ = [
        ("mouse", RID_DEVICE_INFO_MOUSE),
        ("keyboard", RID_DEVICE_INFO_KEYBOARD),
        ("hid", RID_DEVICE_INFO_HID),
    ]


class RID_DEVICE_INFO(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("cbSize", DWORD), ("dwType", DWORD), ("data", RID_DEVICE_INFO_UNION)]


WNDPROC = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(LRESULT, HWND, UINT, WPARAM, LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", UINT),
        ("style", UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", HINSTANCE),
        ("hIcon", HANDLE),
        ("hCursor", HANDLE),
        ("hbrBackground", HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", HANDLE),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", LONG), ("y", LONG)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", HWND),
        ("message", UINT),
        ("wParam", WPARAM),
        ("lParam", LPARAM),
        ("time", DWORD),
        ("pt", POINT),
        ("lPrivate", DWORD),
    ]


@dataclass(slots=True)
class _Failure:
    error: Exception


class _Api:
    def __init__(self) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure()

    def _configure(self) -> None:
        user32 = self.user32
        user32.GetRawInputDeviceList.argtypes = [
            ctypes.POINTER(RAWINPUTDEVICELIST),
            ctypes.POINTER(UINT),
            UINT,
        ]
        user32.GetRawInputDeviceList.restype = UINT
        user32.GetRawInputDeviceInfoW.argtypes = [
            HANDLE,
            UINT,
            ctypes.c_void_p,
            ctypes.POINTER(UINT),
        ]
        user32.GetRawInputDeviceInfoW.restype = UINT
        user32.GetRawInputData.argtypes = [
            HANDLE,
            UINT,
            ctypes.c_void_p,
            ctypes.POINTER(UINT),
            UINT,
        ]
        user32.GetRawInputData.restype = UINT
        user32.RegisterRawInputDevices.argtypes = [
            ctypes.POINTER(RAWINPUTDEVICE),
            UINT,
            UINT,
        ]
        user32.RegisterRawInputDevices.restype = BOOL
        user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
        user32.RegisterClassExW.restype = WORD
        user32.CreateWindowExW.argtypes = [
            DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            HWND,
            HANDLE,
            HINSTANCE,
            ctypes.c_void_p,
        ]
        user32.CreateWindowExW.restype = HWND
        user32.DefWindowProcW.argtypes = [HWND, UINT, WPARAM, LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), HWND, UINT, UINT]
        user32.GetMessageW.restype = BOOL
        user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
        user32.TranslateMessage.restype = BOOL
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
        user32.DispatchMessageW.restype = LRESULT
        user32.PostMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]
        user32.PostMessageW.restype = BOOL
        user32.DestroyWindow.argtypes = [HWND]
        user32.DestroyWindow.restype = BOOL
        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        user32.PostQuitMessage.restype = None
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, HINSTANCE]
        user32.UnregisterClassW.restype = BOOL
        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetModuleHandleW.restype = HINSTANCE

    def error(self, action: str) -> RawInputError:
        code = ctypes.get_last_error()
        return RawInputError(f"{action} failed: {ctypes.WinError(code)}")


class WinRawInputBackend:
    def __init__(self, api: _Api | None = None) -> None:
        self.api = api or _Api()

    def enumerate(self) -> list[RawKeyboardDevice]:
        while True:
            count = UINT()
            result = self.api.user32.GetRawInputDeviceList(
                None, ctypes.byref(count), ctypes.sizeof(RAWINPUTDEVICELIST)
            )
            if result == UINT_ERROR:
                raise self.api.error("GetRawInputDeviceList")
            entries = (RAWINPUTDEVICELIST * count.value)()
            result = self.api.user32.GetRawInputDeviceList(
                entries, ctypes.byref(count), ctypes.sizeof(RAWINPUTDEVICELIST)
            )
            if result != UINT_ERROR:
                break
            if ctypes.get_last_error() != ERROR_INSUFFICIENT_BUFFER:
                raise self.api.error("GetRawInputDeviceList")

        devices: list[RawKeyboardDevice] = []
        for entry in entries[:result]:
            if entry.dwType != RIM_TYPEKEYBOARD:
                continue
            handle = int(entry.hDevice or 0)
            path = self._device_name(handle)
            info = self._device_info(handle)
            devices.append(
                RawKeyboardDevice(
                    len(devices),
                    handle,
                    path,
                    info.keyboard.dwType,
                    info.keyboard.dwSubType,
                    info.keyboard.dwNumberOfKeysTotal,
                )
            )
        return devices

    def open(self, device: RawKeyboardDevice) -> "WinRawKeyboardSession":
        return WinRawKeyboardSession(self.api, device)

    def _device_name(self, handle: int) -> str:
        size = UINT()
        result = self.api.user32.GetRawInputDeviceInfoW(
            HANDLE(handle), RIDI_DEVICENAME, None, ctypes.byref(size)
        )
        if result == UINT_ERROR:
            raise self.api.error("GetRawInputDeviceInfoW(RIDI_DEVICENAME)")
        buffer = ctypes.create_unicode_buffer(size.value + 1)
        result = self.api.user32.GetRawInputDeviceInfoW(
            HANDLE(handle), RIDI_DEVICENAME, buffer, ctypes.byref(size)
        )
        if result == UINT_ERROR:
            raise self.api.error("GetRawInputDeviceInfoW(RIDI_DEVICENAME)")
        return buffer.value.rstrip("\0")

    def _device_info(self, handle: int) -> RID_DEVICE_INFO:
        info = RID_DEVICE_INFO()
        info.cbSize = ctypes.sizeof(RID_DEVICE_INFO)
        size = UINT(ctypes.sizeof(RID_DEVICE_INFO))
        result = self.api.user32.GetRawInputDeviceInfoW(
            HANDLE(handle), RIDI_DEVICEINFO, ctypes.byref(info), ctypes.byref(size)
        )
        if result == UINT_ERROR:
            raise self.api.error("GetRawInputDeviceInfoW(RIDI_DEVICEINFO)")
        return info


class WinRawKeyboardSession:
    def __init__(self, api: _Api, device: RawKeyboardDevice) -> None:
        self.api = api
        self.device = device
        self.events: queue.Queue[RawKeyEvent | _Failure] = queue.Queue()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name="morse-raw-input", daemon=True)
        self.hwnd: int | None = None
        self.start_error: Exception | None = None
        self._wndproc_ref: WNDPROC | None = None
        self.stop_requested = threading.Event()

    def __enter__(self) -> Self:
        self.thread.start()
        if not self.ready.wait(5):
            self.close()
            raise RawInputError("Timed out while starting the Windows Raw Input message loop.")
        if self.start_error is not None:
            raise RawInputError(f"Could not start Windows Raw Input: {self.start_error}")
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def get(self, timeout: float) -> RawKeyEvent | None:
        try:
            item = self.events.get(timeout=timeout)
        except queue.Empty:
            return None
        if isinstance(item, _Failure):
            raise RawInputError(f"Windows Raw Input failed: {item.error}") from item.error
        return item

    def close(self) -> None:
        self.stop_requested.set()
        if self.hwnd is not None:
            self.api.user32.PostMessageW(HWND(self.hwnd), WM_CLOSE, 0, 0)
        if self.thread.is_alive():
            self.thread.join(5)
        if self.thread.is_alive():
            raise RawInputError("Timed out while stopping the Windows Raw Input message loop.")

    def _run(self) -> None:
        class_name = f"MorsePaddleRawInput_{uuid.uuid4().hex}"
        instance = self.api.kernel32.GetModuleHandleW(None)
        self._wndproc_ref = WNDPROC(self._wndproc)
        window_class = WNDCLASSEXW(
            cbSize=ctypes.sizeof(WNDCLASSEXW),
            lpfnWndProc=self._wndproc_ref,
            hInstance=instance,
            lpszClassName=class_name,
        )
        atom = 0
        try:
            atom = self.api.user32.RegisterClassExW(ctypes.byref(window_class))
            if not atom:
                raise self.api.error("RegisterClassExW")
            hwnd = self.api.user32.CreateWindowExW(
                0,
                class_name,
                class_name,
                0,
                0,
                0,
                0,
                0,
                HWND_MESSAGE,
                None,
                instance,
                None,
            )
            if not hwnd:
                raise self.api.error("CreateWindowExW")
            self.hwnd = int(hwnd)
            registration = RAWINPUTDEVICE(0x01, 0x06, RIDEV_INPUTSINK, HWND(hwnd))
            if not self.api.user32.RegisterRawInputDevices(
                ctypes.byref(registration), 1, ctypes.sizeof(RAWINPUTDEVICE)
            ):
                raise self.api.error("RegisterRawInputDevices")
            self.ready.set()
            if self.stop_requested.is_set():
                self.api.user32.PostMessageW(HWND(hwnd), WM_CLOSE, 0, 0)
            message = MSG()
            while True:
                result = self.api.user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == -1:
                    raise self.api.error("GetMessageW")
                if result == 0:
                    break
                self.api.user32.TranslateMessage(ctypes.byref(message))
                self.api.user32.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:  # noqa: BLE001 - worker errors must cross the thread boundary
            if not self.ready.is_set():
                self.start_error = exc
                self.ready.set()
            else:
                self.events.put(_Failure(exc))
        finally:
            if self.hwnd is not None:
                removal = RAWINPUTDEVICE(0x01, 0x06, RIDEV_REMOVE, None)
                self.api.user32.RegisterRawInputDevices(
                    ctypes.byref(removal), 1, ctypes.sizeof(RAWINPUTDEVICE)
                )
                self.api.user32.DestroyWindow(HWND(self.hwnd))
            self.hwnd = None
            if atom:
                self.api.user32.UnregisterClassW(class_name, instance)

    def _wndproc(self, hwnd: HWND, message: int, wparam: int, lparam: int) -> int:
        try:
            if message == WM_INPUT:
                event = self._read_event(lparam)
                if event is not None:
                    self.events.put(event)
                if wparam == RIM_INPUT:
                    return self.api.user32.DefWindowProcW(hwnd, message, wparam, lparam)
                return 0
            if message == WM_CLOSE:
                removal = RAWINPUTDEVICE(0x01, 0x06, RIDEV_REMOVE, None)
                self.api.user32.RegisterRawInputDevices(
                    ctypes.byref(removal), 1, ctypes.sizeof(RAWINPUTDEVICE)
                )
                self.api.user32.DestroyWindow(hwnd)
                return 0
            if message == WM_DESTROY:
                self.hwnd = None
                self.api.user32.PostQuitMessage(0)
                return 0
            return self.api.user32.DefWindowProcW(hwnd, message, wparam, lparam)
        except Exception as exc:  # noqa: BLE001 - ctypes cannot propagate callback exceptions
            self.events.put(_Failure(exc))
            self.api.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return 0

    def _read_event(self, raw_handle: int) -> RawKeyEvent | None:
        size = UINT()
        result = self.api.user32.GetRawInputData(
            HANDLE(raw_handle),
            RID_INPUT,
            None,
            ctypes.byref(size),
            ctypes.sizeof(RAWINPUTHEADER),
        )
        if result == UINT_ERROR:
            raise self.api.error("GetRawInputData")
        storage = (DWORD * ((size.value + 3) // 4))()
        result = self.api.user32.GetRawInputData(
            HANDLE(raw_handle),
            RID_INPUT,
            storage,
            ctypes.byref(size),
            ctypes.sizeof(RAWINPUTHEADER),
        )
        if result == UINT_ERROR:
            raise self.api.error("GetRawInputData")
        header = RAWINPUTHEADER.from_buffer(storage)
        if header.dwType != RIM_TYPEKEYBOARD or int(header.hDevice or 0) != self.device.handle:
            return None
        keyboard = RAWKEYBOARD.from_buffer(storage, ctypes.sizeof(RAWINPUTHEADER))
        if keyboard.MakeCode == 0xFF:
            return None
        return RawKeyEvent(
            timestamp_ns=time.perf_counter_ns(),
            device_handle=self.device.handle,
            device_path=self.device.path,
            is_make=not bool(keyboard.Flags & RI_KEY_BREAK),
            scan_code=keyboard.MakeCode,
            e0=bool(keyboard.Flags & RI_KEY_E0),
            e1=bool(keyboard.Flags & RI_KEY_E1),
            virtual_key=keyboard.VKey,
            message=keyboard.Message,
            extra_information=keyboard.ExtraInformation,
        )
