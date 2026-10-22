"""MAX Chromium launch error diagnostics are bounded and credential-free."""
import pytest

from adapters.max.live_session import _launch_failure_category


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("Executable doesn't exist at /private/profile/path", "missing_executable_or_dependency"),
        ("[Errno 2] No such file or directory", "missing_executable_or_dependency"),
        ("profile appears to be in use by another Chromium process", "chromium_profile_owned"),
        ("SingletonLock failed", "chromium_profile_owned"),
        ("Host system is missing dependencies to run browsers", "missing_system_dependencies"),
        ("error while loading shared libraries: libnss3.so", "missing_system_dependencies"),
        ("No usable sandbox!", "sandbox_failure"),
        ("Failed to move to new namespace", "sandbox_failure"),
        ("Target page, context or browser has been closed", "browser_exited_before_connect"),
        ("Timeout 30000ms exceeded", "launch_timeout"),
        ("Permission denied", "permission_denied"),
        ("No space left on device", "storage_full"),
        ("contains a secret token=supersecret and a private URL", "unclassified"),
    ],
)
def test_launch_failure_is_fixed_category(error, expected):
    assert _launch_failure_category(RuntimeError(error)) == expected


def test_launch_failure_exception_type_does_not_expose_raw_provider_state():
    class PrivateError(Exception):
        pass

    assert _launch_failure_category(PrivateError("SECRET session? auth")) == "unclassified"
