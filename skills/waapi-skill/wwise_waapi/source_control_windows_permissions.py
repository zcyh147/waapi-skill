"""Fixed local Win32 owner/DACL check for confidential provider files.

No provider or network calls. Native Windows acceptance requires a Windows run.
"""
from __future__ import annotations

from pathlib import Path


def require_private_windows_path(path: Path, *, directory: bool) -> None:
    import ctypes
    from ctypes import wintypes
    from .source_control_profiles import ProviderProfileError

    failure = "Provider profile permissions cannot be proved private. Grant access only to the current Windows user on the profile directory and its files, then create a new Draft."
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    void = ctypes.c_void_p
    dword = wintypes.DWORD
    handle = wintypes.HANDLE
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, dword, dword, void, dword, dword, handle]
    kernel.CreateFileW.restype = handle
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = handle
    kernel.CloseHandle.argtypes = [handle]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [void]
    kernel.LocalFree.restype = void
    advapi.OpenProcessToken.argtypes = [handle, dword, ctypes.POINTER(handle)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [handle, ctypes.c_int, void, dword, ctypes.POINTER(dword)]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.GetSecurityInfo.argtypes = [handle, ctypes.c_int, dword, ctypes.POINTER(void), void,
                                      ctypes.POINTER(void), void, ctypes.POINTER(void)]
    advapi.GetSecurityInfo.restype = dword
    advapi.EqualSid.argtypes = [void, void]
    advapi.EqualSid.restype = wintypes.BOOL
    advapi.IsValidSid.argtypes = [void]
    advapi.IsValidSid.restype = wintypes.BOOL
    advapi.GetAclInformation.argtypes = [void, void, dword, ctypes.c_int]
    advapi.GetAclInformation.restype = wintypes.BOOL
    advapi.GetAce.argtypes = [void, dword, ctypes.POINTER(void)]
    advapi.GetAce.restype = wintypes.BOOL

    class SidAttributes(ctypes.Structure):
        _fields_ = [("sid", void), ("attributes", dword)]
    class AclSize(ctypes.Structure):
        _fields_ = [("count", dword), ("used", dword), ("free", dword)]
    class AceHeader(ctypes.Structure):
        _fields_ = [("kind", ctypes.c_ubyte), ("flags", ctypes.c_ubyte), ("size", wintypes.WORD)]

    opened = None
    token = handle()
    security = void()
    try:
        flags = 0x00200000 | (0x02000000 if directory else 0)  # open reparse point; directory backup semantics
        opened = kernel.CreateFileW(str(path), 0x00020000 | 0x80, 7, None, 3, flags, None)
        if opened in (None, ctypes.c_void_p(-1).value):
            raise ProviderProfileError(failure)
        if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            raise ProviderProfileError(failure)
        size = dword()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser
        if size.value <= 0 or size.value > 65536:
            raise ProviderProfileError(failure)
        user_buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, user_buffer, size, ctypes.byref(size)):
            raise ProviderProfileError(failure)
        user_sid = ctypes.cast(user_buffer, ctypes.POINTER(SidAttributes)).contents.sid
        owner, dacl = void(), void()
        if advapi.GetSecurityInfo(opened, 1, 0x1 | 0x4, ctypes.byref(owner), None,
                                  ctypes.byref(dacl), None, ctypes.byref(security)) != 0:
            raise ProviderProfileError(failure)
        if not owner.value or not dacl.value or not advapi.IsValidSid(owner) or not advapi.EqualSid(owner, user_sid):
            raise ProviderProfileError(failure)
        acl = AclSize()
        if not advapi.GetAclInformation(dacl, ctypes.byref(acl), ctypes.sizeof(acl), 2) or acl.count > 256:
            raise ProviderProfileError(failure)
        for index in range(acl.count):
            ace = void()
            if not advapi.GetAce(dacl, index, ctypes.byref(ace)) or not ace.value:
                raise ProviderProfileError(failure)
            header = ctypes.cast(ace, ctypes.POINTER(AceHeader)).contents
            if header.kind == 1:  # A deny ACE grants no access.
                continue
            # Accept only ordinary user-owned allow ACEs. Object/callback ACEs
            # require different semantics and cannot silently pass this proof.
            if header.kind != 0 or header.size < 16:
                raise ProviderProfileError(failure)
            sid = void(ace.value + 8)  # ACE_HEADER + ACCESS_MASK
            if not advapi.IsValidSid(sid) or not advapi.EqualSid(sid, user_sid):
                raise ProviderProfileError(failure)
    except Exception:
        raise ProviderProfileError(failure) from None
    finally:
        if security.value:
            kernel.LocalFree(security)
        if token.value:
            kernel.CloseHandle(token)
        if opened not in (None, ctypes.c_void_p(-1).value):
            kernel.CloseHandle(opened)
