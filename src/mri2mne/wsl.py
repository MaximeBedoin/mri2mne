"""Bridge to run Linux-only tools (FreeSurfer) from the Windows pipeline via WSL2.

Same design as the SimNIBS subprocess bridge: the pipeline stays in the Windows
`mri2mne` environment and shells out to a second world -- here a WSL2 distro --
for the one tool that only exists there. This module owns everything WSL: is it
installed, path translation Windows<->WSL, running a command, and checking that
FreeSurfer is reachable inside the distro.

Nothing here imports mne or simnibs; it is pure process/path plumbing so it can
be unit-tested on any machine (the translation helpers) and smoke-tested wherever
WSL is present (the runners).
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath


class WslError(RuntimeError):
    """Raised when WSL is unavailable or a command inside it fails."""


@dataclass
class WslResult:
    """Outcome of a command run inside WSL."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _wsl_exe() -> str:
    # wsl.exe is always on PATH on a WSL-enabled Windows; keep it overridable in
    # tests by monkeypatching this function rather than hard-coding the string.
    return "wsl.exe"


def to_wsl_path(win_path: str | Path) -> str:
    """Translate a Windows path to its WSL `/mnt/<drive>/...` form.

    Pure-Python (no `wslpath` call) so it is fast and testable offline:
    ``C:\\Users\\me\\t1.nii`` -> ``/mnt/c/Users/me/t1.nii``. UNC and
    already-POSIX paths are passed through unchanged.
    """
    s = str(win_path)
    if s.startswith("/"):
        return s  # already a POSIX path
    pw = PureWindowsPath(s)
    drive = pw.drive  # e.g. "C:"
    if not re.match(r"^[A-Za-z]:$", drive):
        raise WslError(
            f"Cannot translate {s!r} to a WSL path: no drive letter. Use an "
            "absolute Windows path."
        )
    rest = "/".join(pw.parts[1:])  # parts[0] is 'C:\\'
    return f"/mnt/{drive[0].lower()}/{rest}"


def from_wsl_path(wsl_path: str) -> Path:
    """Translate a `/mnt/<drive>/...` WSL path back to a Windows `Path`."""
    m = re.match(r"^/mnt/([A-Za-z])/(.*)$", wsl_path)
    if not m:
        raise WslError(f"{wsl_path!r} is not a translatable /mnt/<drive>/ path.")
    drive, rest = m.group(1).upper(), m.group(2).replace("/", "\\")
    return Path(f"{drive}:\\{rest}")


def is_available(distro: str | None = None) -> bool:
    """True if WSL runs a trivial command (optionally in a named distro)."""
    try:
        res = run("true", distro=distro, check=False, timeout=60)
        return res.ok
    except WslError:
        return False


def run(
    command: str,
    *,
    distro: str | None = None,
    login_shell: bool = True,
    check: bool = True,
    timeout: float | None = None,
    logger: logging.Logger | None = None,
) -> WslResult:
    """Run a bash `command` string inside WSL and capture its output.

    ``login_shell`` sources the user's profile (so FreeSurfer's environment,
    set up in ``~/.bashrc``/``SetUpFreeSurfer.sh``, is present). Raises
    ``WslError`` on failure when ``check`` is set.
    """
    argv = [_wsl_exe()]
    if distro:
        argv += ["-d", distro]
    flags = "-lc" if login_shell else "-c"
    argv += ["-e", "bash", flags, command]

    if logger is not None:
        logger.debug("WSL run: %s", command)

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:  # wsl.exe missing entirely
        raise WslError(
            "wsl.exe not found. Is WSL2 installed? Run `wsl --install` in an "
            "elevated PowerShell."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise WslError(f"WSL command timed out after {timeout}s: {command}") from exc

    result = WslResult(proc.returncode, proc.stdout or "", proc.stderr or "")
    if check and not result.ok:
        raise WslError(
            f"WSL command failed (exit {result.returncode}): {command}\n"
            f"stderr: {result.stderr.strip()}"
        )
    return result


@dataclass
class FreeSurferInfo:
    """What we could learn about FreeSurfer inside the distro."""

    present: bool
    home: str | None
    version: str | None
    has_license: bool
    missing: list[str]  # required binaries not found

    def describe(self) -> str:
        if self.present and self.has_license:
            return f"FreeSurfer {self.version or '?'} at {self.home} (licensed)"
        parts = []
        if not self.present:
            parts.append(
                "FreeSurfer not reachable (FREESURFER_HOME unset or binaries "
                f"missing: {', '.join(self.missing) or 'n/a'})"
            )
        if self.present and not self.has_license:
            parts.append(f"license.txt not found under {self.home}")
        return "; ".join(parts)


# Binaries the volumetric BEM route actually needs (watershed, not recon-all).
_REQUIRED_BINS = ("mri_convert", "mri_watershed")

# Where FreeSurfer may live, tried in order. A user-home install avoids sudo.
_FS_HOME_CANDIDATES = ("$HOME/freesurfer", "/usr/local/freesurfer")


def freesurfer_setup_prefix(freesurfer_home: str | None = None) -> str:
    """A bash snippet that puts FreeSurfer on PATH, for prefixing commands.

    We source ``SetUpFreeSurfer.sh`` explicitly rather than relying on the
    user's ``~/.bashrc``: Ubuntu's default .bashrc returns early for
    non-interactive shells (which is exactly what ``bash -lc`` is), so the
    FreeSurfer lines appended there never run under this bridge.
    """
    if freesurfer_home:
        pick = f'export FREESURFER_HOME="{freesurfer_home}"; '
    else:
        cands = " ".join(f'"{c}"' for c in _FS_HOME_CANDIDATES)
        pick = (
            f"for H in {cands}; do "
            '[ -f "$H/SetUpFreeSurfer.sh" ] && export FREESURFER_HOME="$H" && break; '
            "done; "
        )
    return pick + 'source "$FREESURFER_HOME/SetUpFreeSurfer.sh" >/dev/null 2>&1; '


def run_freesurfer(
    command: str,
    *,
    freesurfer_home: str | None = None,
    distro: str | None = None,
    check: bool = True,
    timeout: float | None = None,
    logger: logging.Logger | None = None,
) -> WslResult:
    """Run `command` with FreeSurfer's environment sourced first."""
    return run(
        freesurfer_setup_prefix(freesurfer_home) + command,
        distro=distro,
        check=check,
        timeout=timeout,
        logger=logger,
    )


def check_freesurfer(
    distro: str | None = None,
    freesurfer_home: str | None = None,
    logger: logging.Logger | None = None,
) -> FreeSurferInfo:
    """Probe the distro for a usable, licensed FreeSurfer (watershed subset)."""
    try:
        res = run(
            freesurfer_setup_prefix(freesurfer_home)
            + "echo \"HOME=$FREESURFER_HOME\"; "
            "echo \"VER=$(cat $FREESURFER_HOME/build-stamp.txt 2>/dev/null)\"; "
            + "; ".join(f"which {b}" for b in _REQUIRED_BINS)
            + "; "
            "for L in \"$FREESURFER_HOME/license.txt\" \"$FREESURFER_HOME/.license\"; "
            "do [ -f \"$L\" ] && echo LICENSE_OK; done",
            distro=distro,
            check=False,
            timeout=120,
            logger=logger,
        )
    except WslError as exc:
        if logger is not None:
            logger.warning("Could not probe FreeSurfer: %s", exc)
        return FreeSurferInfo(False, None, None, False, list(_REQUIRED_BINS))

    out = res.stdout
    home_match = re.search(r"HOME=(.*)", out)
    home = (home_match.group(1).strip() or None) if home_match else None
    ver_match = re.search(r"VER=(.*)", out)
    version = None
    if ver_match and ver_match.group(1).strip():
        version = ver_match.group(1).strip()

    found_bins = {b for b in _REQUIRED_BINS if re.search(rf"/{b}\b", out)}
    missing = [b for b in _REQUIRED_BINS if b not in found_bins]
    present = bool(home) and not missing
    has_license = "LICENSE_OK" in out

    info = FreeSurferInfo(present, home, version, has_license, missing)
    if logger is not None:
        logger.info("FreeSurfer probe: %s", info.describe())
    return info
