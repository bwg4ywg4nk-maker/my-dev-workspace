"""Bounded, offline source capture using descriptor-relative, no-follow paths."""
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import stat
import uuid

from .evidence import _snapshot_id, snapshot_identity

DEFAULT_MAX_SOURCE_BYTES = 8 * 1024 * 1024
CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class SourceSnapshot:
    source_path: str
    media_type: str
    snapshot_id: str
    size_bytes: int

    @property
    def storage_path(self):
        return ".runtime/snapshots/" + self.snapshot_id.split(":", 1)[1]


def _parts(relative_path):
    if type(relative_path) is not str or not relative_path or "\\" in relative_path or "\x00" in relative_path:
        raise ValueError("Expected a repository-relative POSIX path")
    parts = relative_path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("Absolute paths and traversal are forbidden")
    if parts[0] in (".runtime", ".git", ".venv"):
        raise ValueError("Internal directories cannot be source inputs")
    return parts


@contextmanager
def _directory(parent, name, create=False):
    if create:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
        except FileExistsError:
            pass
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        yield fd
    finally:
        os.close(fd)


def _read_regular(fd, limit, check_ctime=True):
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("Source must be a regular file")
    if before.st_size > limit:
        raise ValueError("Source byte limit exceeded")
    chunks = []
    size = 0
    while True:
        chunk = os.read(fd, min(CHUNK_BYTES, limit + 1 - size))
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise ValueError("Source byte limit exceeded")
        chunks.append(chunk)
    after = os.fstat(fd)
    def signature(info):
        values = (info.st_size, info.st_mtime_ns)
        return values + (info.st_ctime_ns,) if check_ctime else values
    if signature(before) != signature(after) or size != after.st_size:
        raise ValueError("File changed during capture")
    return b"".join(chunks)


class SourceStore:
    """Repository root is trusted; source and storage descendants reject symlinks.

    Read-only modes prevent accidental mutation, not attacks by the owning user.
    All reads verify the content hash. No source parsing or decoding is performed.
    """

    def __init__(self, repository_root, max_source_bytes=DEFAULT_MAX_SOURCE_BYTES):
        self.root = Path(repository_root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Repository root must be a directory")
        if type(max_source_bytes) is not int or not 1 <= max_source_bytes <= DEFAULT_MAX_SOURCE_BYTES:
            raise ValueError("Source limit must be between 1 and 8 MiB")
        self.max_source_bytes = max_source_bytes

    @contextmanager
    def _storage(self, create=False):
        with _directory(None, str(self.root)) as root:
            with _directory(root, ".runtime", create=create) as runtime:
                with _directory(runtime, "snapshots", create=create) as snapshots:
                    yield snapshots

    def _read_source(self, parts):
        # Opening each component beneath an already-open directory prevents
        # symlink swaps between a path check and a subsequent file open.
        from contextlib import ExitStack
        with ExitStack() as stack:
            parent = stack.enter_context(_directory(None, str(self.root)))
            for part in parts[:-1]:
                parent = stack.enter_context(_directory(parent, part))
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                return _read_regular(fd, self.max_source_bytes)
            finally:
                os.close(fd)

    def _verified_read(self, parent, name, identity):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            # Unlinking the publication temporary changes ctime/link count.
            # Stored bytes are independently verified by their expected hash.
            data = _read_regular(fd, self.max_source_bytes, check_ctime=False)
        finally:
            os.close(fd)
        if snapshot_identity(data) != identity:
            raise ValueError("Snapshot integrity check failed")
        return data

    def capture(self, relative_path):
        parts = _parts(relative_path)
        extension = Path(parts[-1]).suffix.lower()
        media_types = {".txt": "text/plain", ".csv": "text/csv"}
        if extension not in media_types:
            raise ValueError("Only local .txt and .csv sources are supported")
        data = self._read_source(parts)
        identity = snapshot_identity(data)
        name = identity.split(":", 1)[1]
        with self._storage(create=True) as storage:
            try:
                self._verified_read(storage, name, identity)
            except FileNotFoundError:
                temporary = ".capture-" + uuid.uuid4().hex
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=storage)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(data)
                        stream.flush()
                        os.fchmod(stream.fileno(), 0o400)
                        os.fsync(stream.fileno())
                    try:
                        # Atomic publish without replacing an existing snapshot.
                        os.link(temporary, name, src_dir_fd=storage, dst_dir_fd=storage,
                                follow_symlinks=False)
                    except FileExistsError:
                        self._verified_read(storage, name, identity)
                finally:
                    os.unlink(temporary, dir_fd=storage)
        return SourceSnapshot(relative_path, media_types[extension], identity, len(data))

    def read(self, snapshot_id):
        _snapshot_id(snapshot_id)
        with self._storage() as storage:
            return self._verified_read(storage, snapshot_id.split(":", 1)[1], snapshot_id)
