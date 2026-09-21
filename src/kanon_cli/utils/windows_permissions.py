"""Validate Windows file DACLs without treating POSIX mode bits as ACLs."""

from __future__ import annotations

import ctypes
from ctypes import wintypes as w
from pathlib import Path


def check_private_writers(path: Path) -> None:
    """Reject write grants outside the file owner, SYSTEM and Administrators.

    This intentionally rejects even a grant shadowed by a deny ACE: the
    configuration must express the owner-only policy directly. Unknown ACE
    forms fail closed so an unhandled grant cannot silently weaken the policy.
    """
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer = ctypes.c_void_p
    advapi.GetNamedSecurityInfoW.argtypes = [w.LPWSTR, w.DWORD, w.DWORD] + [ctypes.POINTER(pointer)] * 5
    advapi.GetNamedSecurityInfoW.restype = w.DWORD
    advapi.ConvertSidToStringSidW.argtypes = [pointer, ctypes.POINTER(w.LPWSTR)]
    advapi.ConvertSidToStringSidW.restype = w.BOOL
    advapi.GetAce.argtypes = [pointer, w.DWORD, ctypes.POINTER(pointer)]
    advapi.GetAce.restype = w.BOOL
    kernel.LocalFree.argtypes = [pointer]
    kernel.LocalFree.restype = pointer

    class ACL(ctypes.Structure):
        _fields_ = [
            ("revision", w.BYTE),
            ("reserved", w.BYTE),
            ("size", w.WORD),
            ("count", w.WORD),
            ("reserved2", w.WORD),
        ]

    class ACE(ctypes.Structure):
        _fields_ = [("kind", w.BYTE), ("flags", w.BYTE), ("size", w.WORD), ("mask", w.DWORD)]

    def sid_text(sid):
        text = w.LPWSTR()
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return text.value
        finally:
            kernel.LocalFree(ctypes.cast(text, pointer))

    owner, dacl, descriptor = pointer(), pointer(), pointer()
    status = advapi.GetNamedSecurityInfoW(
        str(path), 1, 5, ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(descriptor)
    )
    if status:
        raise ctypes.WinError(status)
    try:
        if not dacl:
            raise ValueError(f".kanon file has insecure permissions (unrestricted Windows DACL): {path}")
        allowed = {sid_text(owner), "S-1-5-18", "S-1-5-32-544", "S-1-3-4"}
        acl = ctypes.cast(dacl, ctypes.POINTER(ACL)).contents
        for index in range(acl.count):
            entry = pointer()
            if not advapi.GetAce(dacl, index, ctypes.byref(entry)):
                raise ctypes.WinError(ctypes.get_last_error())
            ace = ctypes.cast(entry, ctypes.POINTER(ACE)).contents
            if ace.flags & 8 or ace.kind == 1:
                continue
            if ace.kind != 0:
                raise ValueError(f"Cannot validate .kanon Windows ACL type {ace.kind}: {path}")
            if ace.mask & 0x500D0116:
                trustee = sid_text(entry.value + ctypes.sizeof(ACE))
                if trustee not in allowed:
                    raise ValueError(
                        f".kanon file has insecure permissions (Windows write access for {trustee}): {path}. "
                        "Restrict write access to the file owner, SYSTEM and Administrators in Windows Security settings."
                    )
    finally:
        kernel.LocalFree(descriptor)
