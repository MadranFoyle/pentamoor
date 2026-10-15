"""Calling convention of every function the game's binaries import: how many stack arguments it takes and how many bytes it pops.

The Win32 functions are stdcall: the callee pops its arguments. Their argument counts are the documented parameter counts of the Windows
API (STDCALL below: the functions the game's programs import, by name). The C runtime's (MSVCRTD.DLL) are cdecl and the caller pops, so what a
call out needs is how many words to copy: their prototypes are listed here. Functions that take a variable number of arguments copy
twelve words (the format string uses what it needs; lift_bridge.c reads them off the stack of the lifted code).
"""
VARIADIC_WORDS = 12

# The stdcall functions (kernel32, user32, gdi32, winmm, msvfw32, ...) the game's programs import, with their number of stack arguments.
STDCALL = {
    "AVIFileExit": 0, "AVIFileGetStream": 4, "AVIFileInit": 0, "AVIFileOpenA": 4, "AVIFileRelease": 1, "AVIStreamFindSample": 3, "AVIStreamInfoA": 3,
    "AVIStreamRead": 7, "AVIStreamReadFormat": 4, "AVIStreamRelease": 1, "AVIStreamSampleToTime": 2, "AVIStreamTimeToSample": 2, "AddFontResourceA": 1,
    "AdjustWindowRect": 3, "AnimatePalette": 4, "AppendMenuA": 4, "BeginPaint": 2, "BitBlt": 9, "BringWindowToTop": 1, "CallWindowProcA": 5,
    "CheckDlgButton": 3, "CheckMenuItem": 3, "CheckRadioButton": 4, "ClientToScreen": 2, "CloseHandle": 1, "CompareStringA": 6, "CompareStringW": 6,
    "CopyFileA": 3, "CopyRect": 2, "CreateBitmap": 5, "CreateBrushIndirect": 1, "CreateCompatibleBitmap": 3, "CreateCompatibleDC": 1, "CreateDCA": 4,
    "CreateDIBSection": 6, "CreateDirectoryA": 2, "CreateFileA": 7, "CreateFileMappingA": 6, "CreateFontA": 14, "CreateFontIndirectA": 1,
    "CreateHatchBrush": 2, "CreatePalette": 1, "CreatePen": 3, "CreatePenIndirect": 1, "CreatePolygonRgn": 3, "CreatePopupMenu": 0, "CreateRectRgn": 4,
    "CreateRectRgnIndirect": 1, "CreateSolidBrush": 1, "CreateThread": 6, "CreateWindowExA": 12, "DPtoLP": 3, "DebugBreak": 0, "DeckBuilderMain": 3,
    "DefWindowProcA": 4, "DeleteCriticalSection": 1, "DeleteDC": 1, "DeleteFileA": 1, "DeleteMenu": 3, "DeleteObject": 1, "DestroyCursor": 1,
    "DestroyIcon": 1, "DestroyMenu": 1, "DestroyWindow": 1, "DeviceIoControl": 8, "DialogBoxParamA": 5, "DirectSoundCreate": 3,
    "DisableThreadLibraryCalls": 1, "DispatchMessageA": 1, "DrawDibBegin": 8, "DrawDibClose": 1, "DrawDibDraw": 13, "DrawDibEnd": 1, "DrawDibOpen": 0,
    "DrawDibStart": 2, "DrawDibStop": 1, "DrawFocusRect": 2, "DrawTextA": 5, "DuplicateHandle": 7, "Ellipse": 5, "EnableMenuItem": 3, "EnableWindow": 2,
    "EndDialog": 2, "EndPaint": 2, "EnterCriticalSection": 1, "EnumChildWindows": 3, "ExitProcess": 1, "ExitThread": 1, "FillRect": 3, "FindResourceA": 3,
    "FindWindowA": 2, "FindWindowExA": 4, "FlushFileBuffers": 1, "FormatMessageA": 7, "FrameRect": 3, "FreeEnvironmentStringsA": 1,
    "FreeEnvironmentStringsW": 1, "FreeLibrary": 1, "GdiFlush": 0, "GdiGetBatchLimit": 0, "GdiSetBatchLimit": 1, "GetACP": 0, "GetActiveWindow": 0,
    "GetAsyncKeyState": 1, "GetCPInfo": 2, "GetCapture": 0, "GetCharABCWidthsA": 4, "GetCharWidthA": 4, "GetClassNameA": 3, "GetClientRect": 2,
    "GetCommandLineA": 0, "GetCurrentDirectoryA": 2, "GetCurrentProcess": 0, "GetCurrentThread": 0, "GetCursorPos": 1, "GetDC": 1, "GetDateFormatA": 6,
    "GetDesktopWindow": 0, "GetDeviceCaps": 2, "GetDlgCtrlID": 1, "GetDlgItem": 2, "GetDlgItemInt": 4, "GetDlgItemTextA": 4, "GetDoubleClickTime": 0,
    "GetDriveTypeA": 1, "GetEnvironmentStrings": 0, "GetEnvironmentStringsW": 0, "GetExitCodeThread": 2, "GetFileSize": 2, "GetFileType": 1, "GetFocus":
    0, "GetKeyState": 1, "GetLastError": 0, "GetLocalTime": 1, "GetMenu": 1, "GetMenuItemCount": 1, "GetMessageA": 4, "GetMessageTime": 0,
    "GetModuleFileNameA": 3, "GetModuleHandleA": 1, "GetOEMCP": 0, "GetObjectA": 3, "GetOpenFileNameA": 1, "GetPaletteEntries": 4, "GetParent": 1,
    "GetPixel": 3, "GetPriorityClass": 1, "GetPrivateProfileIntA": 4, "GetPrivateProfileStringA": 6, "GetProcAddress": 2, "GetSaveFileNameA": 1,
    "GetScrollPos": 2, "GetScrollRange": 4, "GetStartupInfoA": 1, "GetStdHandle": 1, "GetStockObject": 1, "GetStringTypeA": 5, "GetStringTypeW": 4,
    "GetSubMenu": 2, "GetSysColor": 1, "GetSystemMetrics": 1, "GetSystemTime": 1, "GetTextAlign": 1, "GetTextExtentPoint32A": 4, "GetTextExtentPointA": 4,
    "GetTextMetricsA": 2, "GetThreadPriority": 1, "GetTickCount": 0, "GetTimeZoneInformation": 1, "GetTopWindow": 1, "GetVersion": 0, "GetWindow": 2,
    "GetWindowDC": 1, "GetWindowLongA": 2, "GetWindowRect": 2, "GetWindowTextA": 3, "GetWindowThreadProcessId": 2, "GetWindowWord": 2, "GlobalAlloc": 2,
    "GlobalFree": 1, "GlobalHandle": 1, "GlobalLock": 1, "GlobalUnlock": 1, "HeapAlloc": 3, "HeapCreate": 3, "HeapDestroy": 1, "HeapFree": 3,
    "HeapReAlloc": 4, "HeapValidate": 3, "ICClose": 1, "ICDrawBegin": 15, "ICLocate": 5, "ICSendMessage": 4, "InflateRect": 3,
    "InitializeCriticalSection": 1, "InsertMenuA": 5, "InterlockedDecrement": 1, "InterlockedIncrement": 1, "IntersectClipRect": 5, "IntersectRect": 3,
    "InvalidateRect": 3, "IsBadReadPtr": 2, "IsBadWritePtr": 2, "IsDlgButtonChecked": 2, "IsIconic": 1, "IsRectEmpty": 1, "IsWindowVisible": 1,
    "KillTimer": 2, "LCMapStringA": 6, "LCMapStringW": 6, "LPtoDP": 3, "LeaveCriticalSection": 1, "LineTo": 3, "LoadAcceleratorsA": 2, "LoadBitmapA": 2,
    "LoadCursorA": 2, "LoadIconA": 2, "LoadLibraryA": 1, "LoadResource": 2, "LocalFree": 1, "LockResource": 1, "LockWindowUpdate": 1, "MCIWndCreateA": 4,
    "MapViewOfFile": 5, "MapWindowPoints": 4, "MessageBeep": 1, "MessageBoxA": 4, "ModifyMenuA": 5, "MoveToEx": 4, "MoveWindow": 6, "MultiByteToWideChar":
    6, "OffsetRect": 3, "OffsetViewportOrgEx": 4, "OutputDebugStringA": 1, "PeekMessageA": 5, "PostMessageA": 4, "PostQuitMessage": 1, "PtInRect": 2,
    "ReadFile": 5, "RealizePalette": 1, "Rectangle": 5, "RegCloseKey": 1, "RegCreateKeyExA": 9, "RegFlushKey": 1, "RegOpenKeyExA": 5, "RegQueryValueExA":
    6, "RegSetValueExA": 6, "RegisterClassA": 1, "ReleaseCapture": 0, "ReleaseDC": 2, "RemoveFontResourceA": 1, "RemoveMenu": 3, "RestoreDC": 2,
    "RoundRect": 7, "RtlUnwind": 4, "SHAppBarMessage": 2, "SaveDC": 1, "ScreenToClient": 2, "ScrollWindow": 5, "SelectClipRgn": 2, "SelectObject": 2,
    "SelectPalette": 3, "SendDlgItemMessageA": 5, "SendMessageA": 4, "SetActiveWindow": 1, "SetBitmapDimensionEx": 4, "SetBkColor": 2, "SetBkMode": 2,
    "SetCapture": 1, "SetClassLongA": 3, "SetConsoleCtrlHandler": 2, "SetCurrentDirectoryA": 1, "SetCursor": 1, "SetCursorPos": 2, "SetDIBColorTable": 4,
    "SetDIBits": 7, "SetDIBitsToDevice": 12, "SetDlgItemInt": 4, "SetDlgItemTextA": 3, "SetEndOfFile": 1, "SetEnvironmentVariableA": 2, "SetFilePointer":
    4, "SetFocus": 1, "SetForegroundWindow": 1, "SetHandleCount": 1, "SetMapMode": 2, "SetPaletteEntries": 4, "SetParent": 2, "SetPixel": 4, "SetPixelV":
    4, "SetPriorityClass": 2, "SetROP2": 2, "SetRect": 5, "SetRectRgn": 5, "SetScrollPos": 4, "SetScrollRange": 5, "SetStdHandle": 2, "SetStretchBltMode":
    2, "SetSystemPaletteUse": 2, "SetTextAlign": 2, "SetTextColor": 2, "SetThreadPriority": 2, "SetTimer": 4, "SetViewportExtEx": 4, "SetViewportOrgEx":
    4, "SetWindowExtEx": 4, "SetWindowLongA": 3, "SetWindowOrgEx": 4, "SetWindowPos": 7, "SetWindowRgn": 3, "SetWindowTextA": 2, "SetWindowWord": 3,
    "ShowCursor": 1, "ShowWindow": 2, "Sleep": 1, "StretchBlt": 11, "TerminateProcess": 2, "TextOutA": 5, "TrackPopupMenu": 7, "TranslateAcceleratorA": 3,
    "TranslateMessage": 1, "UnhandledExceptionFilter": 1, "UnionRect": 3, "UnmapViewOfFile": 1, "UnrealizeObject": 1, "UnregisterClassA": 2,
    "UpdateWindow": 1, "VirtualAlloc": 4, "VirtualFree": 3, "WaitForSingleObject": 2, "WideCharToMultiByte": 8, "WinHelpA": 4, "WindowFromPoint": 1,
    "WriteFile": 5, "_lclose": 1, "_lopen": 2, "lstrcatA": 2, "lstrcpyA": 2, "lstrlenA": 1, "mmioAdvance": 3, "mmioAscend": 3, "mmioClose": 2,
    "mmioDescend": 4, "mmioGetInfo": 3, "mmioOpenA": 3, "mmioRead": 3, "mmioSeek": 3, "mmioSetInfo": 3, "timeBeginPeriod": 1, "timeEndPeriod": 1,
    "timeGetDevCaps": 2, "timeGetTime": 0, "timeKillEvent": 1, "timeSetEvent": 5, "waveOutWrite": 3, "wsprintfA": 3, "wvsprintfA": 3
}

CDECL = {
    "??2@YAPAXI@Z": 1, "??3@YAXPAX@Z": 1, "_CrtDbgReport": 5, "_XcptFilter": 2, "__CxxFrameHandler": 4, "__dllonexit": 3,
    "__getmainargs": 5, "__p___argv": 0, "__p___mb_cur_max": 0, "__p__acmdln": 0, "__p__commode": 0, "__p__fmode": 0, "__p__pctype": 0,
    "__set_app_type": 1, "__setusermatherr": 1, "_assert": 3, "_chdir": 1, "_close": 1, "_controlfp": 2, "_errno": 0,
    "_except_handler3": 4, "_exit": 1, "_expand": 2, "_filelength": 1, "_fileno": 1, "_free_dbg": 2, "_ftol": 0, "_getcwd": 2,
    "_initterm": 2, "_isctype": 2, "_itoa": 3, "_lseek": 3, "_malloc_dbg": 5, "_mkdir": 1, "_msize": 1, "_onexit": 1, "_open": 3,
    "_read": 3, "_splitpath": 5, "_strcmpi": 2, "_stricmp": 2, "_strlwr": 1, "_strnicmp": 3, "_tell": 1, "_vsnprintf": 4,
    "_write": 3, "abs": 1, "atoi": 1, "bsearch": 5, "clock": 0, "ctime": 1, "exit": 1, "fclose": 1, "fgetc": 1, "fgets": 3,
    "fopen": 2, "fprintf": VARIADIC_WORDS, "fread": 4, "free": 1, "fscanf": VARIADIC_WORDS, "fseek": 3, "ftell": 1, "fwrite": 4,
    "malloc": 1, "memchr": 3, "memcmp": 3, "memcpy": 3, "memmove": 3, "memset": 3, "rand": 0, "realloc": 2, "sprintf": VARIADIC_WORDS,
    "srand": 1, "sscanf": VARIADIC_WORDS, "strcat": 2, "strchr": 2, "strcmp": 2, "strcpy": 2, "strcspn": 2, "strlen": 1,
    "strncat": 3, "strncmp": 3, "strncpy": 3, "strrchr": 2, "strspn": 2, "time": 1, "tolower": 1,
}
# user32's wsprintfA is cdecl too
CDECL_OTHER = {("user32.dll", "wsprintfA"): VARIADIC_WORDS, ("msvfw32.dll", "MCIWndCreateA"): 4}      # MCIWndCreateA is VFWAPIV: cdecl

# stdcall functions only the DLLs import
EXTRA_STDCALL = {"GetNearestPaletteIndex": 2}
# functions that take a POINT by value, which is two stack words (STDCALL counts the point as one argument, as the C prototype writes it)
POINT_BY_VALUE = {"PtInRect": 3, "WindowFromPoint": 2, "ChildWindowFromPoint": 3, "DragDetect": 3, "RealChildWindowFromPoint": 3}


def signature(dll, name):
    """(stack words to copy, bytes the callee pops) for the import `name` of `dll`, or None if it is not known."""
    dll = dll.lower()
    if dll.startswith("msvcrt"):
        n = CDECL.get(name)
        return None if n is None else (n, 0)
    if (dll, name) in CDECL_OTHER:
        return (CDECL_OTHER[(dll, name)], 0)
    n = POINT_BY_VALUE.get(name, STDCALL.get(name, EXTRA_STDCALL.get(name)))
    return None if n is None else (n, 4 * n)
