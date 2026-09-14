"""Closed executor-artifact importer; no URL, traversal or symlink source ingress."""
from __future__ import annotations
import hashlib
import os
import stat
from pathlib import Path
from adapters.imagegen import ImagegenArtifact
from .assets import VerifiedImage, verify_image
from .domain import DomainError


def verified_artifact(root: Path, manifest: ImagegenArtifact) -> VerifiedImage:
    if not isinstance(manifest.ref, str) or len(manifest.ref) > 256:
        raise DomainError('imagegen_artifact_reference_invalid')
    path = Path(manifest.ref)
    if path.is_absolute() or path.parts != (manifest.ref,) or manifest.ref in {'.','..'} or '\\' in manifest.ref:
        raise DomainError('imagegen_artifact_reference_invalid')
    if type(manifest.size) is not int or not 1 <= manifest.size <= 20*1024*1024:
        raise DomainError('imagegen_artifact_size_invalid')
    # The executor root is trusted; its per-job directory is not. Do not resolve
    # a job-directory symlink before O_NOFOLLOW (that would defeat confinement).
    base = Path(root).absolute()
    try:
        directory = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        raise DomainError('imagegen_artifact_not_available') from None
    try:
        fd = os.open(manifest.ref, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != manifest.size:
                raise DomainError('imagegen_artifact_size_invalid')
            data = source.read(manifest.size+1)
    except OSError:
        raise DomainError('imagegen_artifact_not_available') from None
    finally:
        os.close(directory)
    if len(data) != manifest.size or hashlib.sha256(data).hexdigest() != manifest.sha256:
        raise DomainError('imagegen_artifact_hash_mismatch')
    verified = verify_image(data, manifest.mime)
    if (verified.width, verified.height) != (manifest.width, manifest.height):
        raise DomainError('imagegen_artifact_dimensions_mismatch')
    return verified
