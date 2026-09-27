"""Trusted-admin deployment protection; never a provider qualification API.

Root, the kernel, and the administrator provisioning the fixed pin file are
trusted for the process lifetime. No administrator may change this deployment
until process exit. Checks detect loss; permissions/read-only storage prevent
unprivileged changes between checks. This module does not authorize a launcher.
"""
import ctypes
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import plistlib
import stat
import subprocess
import sys
import threading

from .evidence import canonical_bytes
from ._provider_manifests import _require


_PIN_FILE = Path('/Library/ProfessionalPresentationAgent/deployment-protection.json')
_FIELDS = {'kind', 'root', 'backing_file', 'backing_sha256',
           'deployment_sha256', 'build_sha256', 'launch_policy_sha256',
           'inputs_sha256'}


class _StatFS(ctypes.Structure):
    # Darwin's 64-bit statfs ABI (sys/mount.h); only supported on native macOS.
    _fields_ = [('bsize', ctypes.c_uint32), ('iosize', ctypes.c_int32),
                ('blocks', ctypes.c_uint64), ('bfree', ctypes.c_uint64),
                ('bavail', ctypes.c_uint64), ('files', ctypes.c_uint64),
                ('ffree', ctypes.c_uint64), ('fsid', ctypes.c_int32 * 2),
                ('owner', ctypes.c_uint32), ('type', ctypes.c_uint32),
                ('flags', ctypes.c_uint32), ('subtype', ctypes.c_uint32),
                ('fstype', ctypes.c_char * 16), ('mounted', ctypes.c_char * 1024),
                ('source', ctypes.c_char * 1024), ('flags_ext', ctypes.c_uint32),
                ('reserved', ctypes.c_uint32 * 7)]


def _libc():
    _require(sys.platform == 'darwin' and ctypes.sizeof(ctypes.c_void_p) == 8,
             'unsupported deployment protection platform')
    lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    lib.statfs64 = getattr(lib, 'fstatfs$INODE64')
    lib.statfs64.argtypes = [ctypes.c_int, ctypes.POINTER(_StatFS)]
    lib.statfs64.restype = ctypes.c_int
    lib.acl_get_fd_np.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.acl_get_fd_np.restype = ctypes.c_void_p
    lib.acl_get_entry.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                 ctypes.POINTER(ctypes.c_void_p)]
    lib.acl_get_entry.restype = ctypes.c_int
    lib.acl_free.argtypes = [ctypes.c_void_p]
    lib.acl_free.restype = ctypes.c_int
    return lib


def _mount(fd):
    value = _StatFS()
    _require(_libc().statfs64(fd, ctypes.byref(value)) == 0,
             'mount observation unavailable')
    return (tuple(value.fsid), value.owner, value.flags, value.fstype.decode(),
            os.fsdecode(value.mounted), os.fsdecode(value.source))


def _no_acl(fd):
    # Deliberately narrow: even harmless ACLs are unsupported, never ignored.
    lib = _libc()
    ctypes.set_errno(0)
    acl = lib.acl_get_fd_np(fd, 0x100)  # ACL_TYPE_EXTENDED
    if not acl and ctypes.get_errno() == errno.ENOENT:
        return  # Darwin: no extended ACL on this already-open descriptor.
    _require(bool(acl), 'path ACL observation unavailable')
    try:
        entry = ctypes.c_void_p()
        ctypes.set_errno(0)
        _require(lib.acl_get_entry(acl, 0, ctypes.byref(entry)) == -1 and
                 ctypes.get_errno() == errno.EINVAL,
                 'deployment protection requires an empty ACL')
    finally:
        lib.acl_free(acl)


def _stamp(info):
    base = (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            getattr(info, 'st_flags', 0))
    return base if stat.S_ISDIR(info.st_mode) else base + (
        info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _path(value):
    _require(type(value) is str and value.startswith('/'), 'absolute protected path')
    path = Path(value)
    _require(str(path) == value and path.resolve(strict=True) == path,
             'noncanonical or symlinked protected path')
    return path


def _inspect(path, directory, *, admin=False, mount=None, read=False):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    if directory:
        flags |= os.O_DIRECTORY
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        _require((stat.S_ISDIR if directory else stat.S_ISREG)(before.st_mode),
                 'protected path type')
        observed = _mount(fd)
        _require(not observed[2] & 0x20, 'union/overlay mount prohibited')
        if admin:
            _require(observed[1] == 0 and observed[2] & 0x1000 and
                     not observed[2] & 0x200000,
                     'local administrator-mounted path with ownership required')
            _require(before.st_uid == 0 and not before.st_mode & 0o022,
                     'administrator-owned non-writable path required')
            _no_acl(fd)
        if mount is not None:
            _require(observed == mount and bool(observed[2] & 1),
                     'writable mount or artifact escaping protected deployment')
        digest = sha256()
        data = bytearray()
        if not directory:
            for chunk in iter(lambda: os.read(fd, 1024 * 1024), b''):
                digest.update(chunk)
                if read:
                    data.extend(chunk)
                    _require(len(data) <= 1024 * 1024, 'oversized protection pins')
        _require(_stamp(before) == _stamp(os.fstat(fd)) == _stamp(path.lstat()),
                 'protected path changed during observation')
        _require(_mount(fd) == observed, 'mount changed during observation')
        return (_stamp(before), observed, None if directory else digest.hexdigest()), bytes(data)
    finally:
        os.close(fd)


def _admin_chain(path, *, read=False):
    result = []
    for ancestor in reversed(path.parents):
        result.append(_inspect(ancestor, True, admin=True)[0])
    record, data = _inspect(path, path.is_dir(), admin=True, read=read)
    return tuple(result + [record]), data


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate protection pin')
        result[key] = value
    return result


def _pins():
    path = _path(str(_PIN_FILE))
    chain, raw = _admin_chain(path, read=True)
    _require(path.is_file(), 'protection pin file required')
    pins = json.loads(raw, object_pairs_hook=_unique)
    _require(type(pins) is dict and set(pins) == _FIELDS and
             pins['kind'] == 'trusted-admin-readonly-image-v1', 'protection pin schema')
    for key in _FIELDS - {'kind', 'root', 'backing_file'}:
        value = pins[key]
        _require(type(value) is str and len(value) == 64 and
                 all(c in '0123456789abcdef' for c in value), 'protection digest')
    return pins, (chain, sha256(raw).hexdigest())


def _attachment(root, mount, backing):
    result = subprocess.run(['/usr/bin/hdiutil', 'info', '-plist'], env={},
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
    _require(result.returncode == 0 and len(result.stdout) <= 8 * 1024 * 1024,
             'image attachment observation unavailable')
    info = plistlib.loads(result.stdout)
    matches = []
    for image in info['images']:
        entities = image['system-entities']
        if any(e.get('mount-point') == str(root) for e in entities):
            matches.append(image)
    _require(len(matches) == 1, 'ambiguous or missing deployment image')
    image = matches[0]
    _require(image.get('writeable') is False and
             image.get('image-type') == 'read-only disk image' and
             image.get('owner-uid') == 0, 'writable or non-admin image attachment')
    # Reject shadow metadata even when the shadow is currently read-only.
    def no_overlay(value):
        if isinstance(value, dict):
            for key, child in value.items():
                _require(not any(s in key.lower() for s in ('shadow', 'overlay')),
                         'shadow/overlay image prohibited')
                no_overlay(child)
        elif isinstance(value, list):
            for child in value:
                no_overlay(child)
    no_overlay(image)
    _require(image.get('image-path') == str(backing), 'backing-store mismatch')
    mounted = [e for e in image['system-entities'] if 'mount-point' in e]
    _require(len(mounted) == 1 and mounted[0]['mount-point'] == str(root) and
             mounted[0]['dev-entry'] == mount[5], 'image device/mount mismatch')
    # Entire attachment record, including device names/helper PID, is retained.
    return plistlib.dumps(image, sort_keys=True)


def _inputs(build_files, native_files, module_paths, runtime):
    return {'build_files': {k: str(v) for k, v in build_files.items()},
            'native_files': {k: str(v) for k, v in native_files.items()},
            'module_paths': [str(p) for p in module_paths], 'runtime': runtime}


def _digest(value):
    return sha256(canonical_bytes(value)).hexdigest()


class _Lifecycle:
    """One process, one immutable deployment; observed failures latch forever.

    Used only by the offline prerequisite boundary. No result is a native
    lifecycle credential and there is no reset/requalification API.
    """
    def __init__(self):
        self.pid = os.getpid()
        self.invalid = False
        self.snapshot = None
        self._state_lock = threading.Lock()
        # Retain this process-lifetime state; never inherit a possibly locked
        # parent mutex. Replacing the child mutex does not restore validity.
        os.register_at_fork(after_in_child=self._after_fork)

    def _after_fork(self):
        self.invalid = True
        self._state_lock = threading.Lock()

    def _check_process(self):
        # Check before acquiring any mutex, including in reject's error path.
        if self.pid != os.getpid():
            self.invalid = True
            _require(False, 'deployment protection lifecycle invalid')

    def reject(self):
        if self.pid != os.getpid():
            self.invalid = True
            return
        with self._state_lock:
            self.invalid = True

    def check(self, args):
        try:
            self._check_process()
            with self._state_lock:
                self._check_process()
                _require(not self.invalid, 'deployment protection lifecycle invalid')
            # Do not hold the state mutex across I/O: another failed check must
            # be able to latch invalidation while this observation is in flight.
            expected, build, build_files, native_files, module_paths, runtime = args
            pins, authentication = _pins()
            _require(_digest(expected) == pins['deployment_sha256'] and
                     _digest(build) == pins['build_sha256'] and
                     _digest(_inputs(build_files, native_files, module_paths, runtime)) ==
                     pins['inputs_sha256'], 'authenticated evidence-pin mismatch')
            root, backing = _path(pins['root']), _path(pins['backing_file'])
            _require(not backing.is_relative_to(root) and
                     not _PIN_FILE.is_relative_to(root), 'independent backing store/pins required')
            root_chain, _ = _admin_chain(root)
            backing_chain, _ = _admin_chain(backing)
            _require(backing.is_file() and backing_chain[-1][2] == pins['backing_sha256'],
                     'backing-store mismatch')
            mount = root_chain[-1][1]
            _require(mount[1] == 0 and mount[2] & 1 and mount[2] & 0x1000 and
                     not mount[2] & (0x20 | 0x200000) and
                     mount[3] in ('hfs', 'apfs') and mount[4] == str(root),
                     'writable, overlay, or unsupported deployment mount')
            attachment = _attachment(root, mount, backing)
            paths = set()
            for value in (*build_files.values(), *native_files.values(), *module_paths):
                path = _path(str(value))
                _require(path.is_relative_to(root), 'artifact escaping protected deployment')
                paths.add(path)
                paths.update(p for p in path.parents if p.is_relative_to(root))
            for value in module_paths:
                pending = [_path(str(value))]
                while pending:
                    directory = pending.pop()
                    _inspect(directory, True, mount=mount)
                    for child in directory.iterdir():
                        child = _path(str(child))
                        paths.add(child)
                        if child.is_dir():
                            pending.append(child)
            records = tuple((str(p), _inspect(p, p.is_dir(), mount=mount)[0])
                            for p in sorted(paths))
            snapshot = (authentication, root_chain, backing_chain, attachment, records)
            self._check_process()
            with self._state_lock:
                try:
                    self._check_process()
                    _require(not self.invalid, 'deployment protection lifecycle invalid')
                    _require(self.snapshot is None or self.snapshot == snapshot,
                             'deployment protection/mount identity changed')
                    self.snapshot = snapshot
                    # Success and rejection have one synchronized publication
                    # point. An invalidated observation cannot publish success.
                    return pins
                except BaseException:
                    self.invalid = True
                    raise
        except BaseException:
            self.reject()
            raise


_lifecycle = _Lifecycle()


def collect_protected_evidence(*args):
    """Provisioning-only candidate evidence; never approve its own expected pin.

    An administrator first installs the other authenticated pins, then collects
    this candidate and independently installs its digest as launch_policy_sha256.
    The process performing require() must start after that provisioning step.
    """
    from . import _launch_policy as policy
    observation = _Lifecycle()

    def boundary(native_files, module_paths):
        observation.check(args)
        return observation.snapshot

    result = policy._collect(*args, resolution=boundary,
                             checkpoint=lambda: observation.check(args))
    observation.check(args)
    return result


def require(*args):
    """Recheck before/after every evidence-use boundary; return no credential.

    Each subsequent call retains the original mount/path/pin identities. The
    trusted administrator must maintain them until process exit, including
    intervals between checks. A failed call permanently invalidates this process.
    """
    from . import _launch_policy as policy
    try:
        pins = _lifecycle.check(args)

        def boundary(native_files, module_paths):
            _lifecycle.check(args)
            return _lifecycle.snapshot

        actual = policy._collect(*args, resolution=boundary,
                                 checkpoint=lambda: _lifecycle.check(args))
        _require(_digest(actual) == pins['launch_policy_sha256'],
                 'authenticated launch-policy evidence-pin mismatch')
        _lifecycle.check(args)
    except BaseException:
        _lifecycle.reject()
        raise
