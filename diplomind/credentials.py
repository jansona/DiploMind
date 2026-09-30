"""Pinned server credential reference, resolved only when a provider is started.

The reader never creates, changes, prints, or caches the credential file. All
errors use fixed codes so exception messages cannot reveal contents or paths.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat


_ALLOWED_KEY_ROOT = Path(__file__).resolve().parents[2] / "diplomind-private"
MAX_KEY_BYTES = 8192


class CredentialError(ValueError):
    """Fixed, non-sensitive configuration or credential-read failure."""


def pinned_key_file() -> Path:
    return _ALLOWED_KEY_ROOT / "api-key.txt"


def validate_key_file_reference(*, api: str, api_key: str | None,
                                api_key_file: object) -> str | None:
    """Validate the server-only reference without inspecting the filesystem."""
    if api_key_file is None:
        return None
    if type(api_key_file) is not str or api_key_file != str(pinned_key_file()):
        raise CredentialError("credential_reference_invalid")
    if api != "openai":
        raise CredentialError("credential_provider_unsupported")
    if api_key is not None:
        raise CredentialError("credential_sources_conflict")
    return api_key_file


def _read_pinned_key() -> str:
    directory_fd = file_fd = None
    try:
        # Walk from the root using descriptor-relative opens. O_NOFOLLOW on the
        # final directory alone would still follow symlinks in its ancestors.
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        directory_fd = os.open(_ALLOWED_KEY_ROOT.anchor, flags)
        for component in _ALLOWED_KEY_ROOT.parts[1:]:
            next_fd = os.open(component, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        directory = os.fstat(directory_fd)
        if directory.st_uid != os.geteuid() or stat.S_IMODE(directory.st_mode) != 0o700:
            raise CredentialError("credential_file_unsafe")
        file_fd = os.open("api-key.txt", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                          dir_fd=directory_fd)
        info = os.fstat(file_fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_size > MAX_KEY_BYTES):
            raise CredentialError("credential_file_unsafe")
        with os.fdopen(file_fd, "rb") as source:
            file_fd = None
            raw = source.read(MAX_KEY_BYTES + 1)
        if len(raw) > MAX_KEY_BYTES:
            raise CredentialError("credential_file_unsafe")
        raw = raw.rstrip(b"\r\n")  # a text editor's final newline is harmless
        if not raw:
            raise CredentialError("credential_empty")
        # A single bare token, not shell assignments, quotes, JSON, or headers.
        if re.fullmatch(rb"[A-Za-z0-9][A-Za-z0-9._-]*", raw) is None:
            raise CredentialError("credential_invalid")
        return raw.decode("ascii")
    except CredentialError:
        raise
    except (OSError, ValueError):
        raise CredentialError("credential_file_unsafe") from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def resolve_api_key(*, api: str, api_key: str | None, api_key_file: object) -> str | None:
    """Resolve one approved source without storing the result back in Config."""
    reference = validate_key_file_reference(api=api, api_key=api_key, api_key_file=api_key_file)
    return api_key if reference is None else _read_pinned_key()
