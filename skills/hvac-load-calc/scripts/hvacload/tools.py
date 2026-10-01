"""Locate, download and verify the pinned engines (OpenStudio + EnergyPlus, OpenStudio-HPXML).

Nothing here is bundled with the skill: releases are fetched from their official
GitHub release pages into HVACLOAD_HOME (default ~/.hvacload).
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

OPENSTUDIO_VERSION = "3.11.0"
OPENSTUDIO_BUILD = "241b8abb4d"
OSHPXML_VERSION = "v1.12.0"
ENERGYPLUS_VERSION = "25.2"  # bundled inside OpenStudio 3.11.0

_OS_BASE = f"https://github.com/NatLabRockies/OpenStudio/releases/download/v{OPENSTUDIO_VERSION}/"
_OSHPXML_URL = (
    "https://github.com/NatLabRockies/OpenStudio-HPXML/releases/download/"
    f"{OSHPXML_VERSION}/OpenStudio-HPXML-{OSHPXML_VERSION}.zip"
)


def home() -> Path:
    return Path(os.environ.get("HVACLOAD_HOME", Path.home() / ".hvacload")).expanduser()


def tools_dir() -> Path:
    return home() / "tools"


def weather_dir() -> Path:
    return home() / "weather"


def _openstudio_asset() -> str:
    stem = f"OpenStudio-{OPENSTUDIO_VERSION}%2B{OPENSTUDIO_BUILD}"
    system, machine = platform.system(), platform.machine().lower()
    if system == "Windows":
        return f"{stem}-Windows.tar.gz"
    if system == "Darwin":
        return f"{stem}-Darwin-{'arm64' if machine in ('arm64', 'aarch64') else 'x86_64'}.tar.gz"
    if system == "Linux":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
        ubuntu = "22.04"
        try:
            osr = Path("/etc/os-release").read_text()
            if 'VERSION_ID="24' in osr:
                ubuntu = "24.04"
        except OSError:
            pass
        return f"{stem}-Ubuntu-{ubuntu}-{arch}.tar.gz"
    raise SystemExit(f"Unsupported platform {system} {machine}")


def openstudio_root() -> Path | None:
    """Return the extracted OpenStudio folder (contains bin/ and EnergyPlus/)."""
    env = os.environ.get("HVACLOAD_OPENSTUDIO")
    if env:
        return Path(env)
    base = tools_dir()
    if not base.exists():
        return None
    for cand in sorted(base.glob(f"OpenStudio-{OPENSTUDIO_VERSION}*")):
        if (cand / "bin").exists():
            return cand
        # some tarballs nest one more level
        for sub in cand.iterdir() if cand.is_dir() else []:
            if (sub / "bin").exists():
                return sub
    return None


def openstudio_exe() -> Path | None:
    root = openstudio_root()
    if not root:
        return None
    exe = root / "bin" / ("openstudio.exe" if os.name == "nt" else "openstudio")
    return exe if exe.exists() else None


def energyplus_exe() -> Path | None:
    env = os.environ.get("HVACLOAD_ENERGYPLUS")
    if env:
        return Path(env)
    root = openstudio_root()
    if not root:
        return None
    for name in ("energyplus.exe", "energyplus"):
        exe = root / "EnergyPlus" / name
        if exe.exists():
            return exe
    return None


def oshpxml_root() -> Path | None:
    env = os.environ.get("HVACLOAD_OSHPXML")
    if env:
        return Path(env)
    base = tools_dir()
    for cand in sorted(base.glob("OpenStudio-HPXML*")) if base.exists() else []:
        if (cand / "workflow" / "run_simulation.rb").exists():
            return cand
    return None


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"downloading {url}", flush=True)
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, -1
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            pct = int(done * 100 / total) if total else -1
            if total and pct // 10 != last:
                last = pct // 10
                print(f"  {pct}% of {total / 1e6:.0f} MB", flush=True)
    tmp.replace(dest)


def setup(force: bool = False) -> dict:
    tdir = tools_dir()
    tdir.mkdir(parents=True, exist_ok=True)
    if force or not openstudio_exe():
        asset = _openstudio_asset()
        archive = tdir / asset.replace("%2B", "+")
        if not archive.exists():
            _download(_OS_BASE + asset, archive)
        print("extracting OpenStudio (this takes a few minutes)...", flush=True)
        with tarfile.open(archive) as tf:
            tf.extractall(tdir, filter="data") if sys.version_info >= (3, 12) else tf.extractall(tdir)
        archive.unlink()
    if force or not oshpxml_root():
        archive = tdir / f"OpenStudio-HPXML-{OSHPXML_VERSION}.zip"
        if not archive.exists():
            _download(_OSHPXML_URL, archive)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(tdir)
        archive.unlink()
        # release zips extract to OpenStudio-HPXML/; pin the version in the folder name
        plain = tdir / "OpenStudio-HPXML"
        if plain.exists():
            target = tdir / f"OpenStudio-HPXML-{OSHPXML_VERSION}"
            if target.exists():
                shutil.rmtree(target)
            plain.rename(target)
    return doctor()


def doctor() -> dict:
    """Report which engines are available and their versions."""
    rep: dict = {"home": str(home()), "python": sys.version.split()[0], "platform": platform.platform()}
    os_exe, ep_exe, osh = openstudio_exe(), energyplus_exe(), oshpxml_root()
    rep["openstudio"] = str(os_exe) if os_exe else None
    rep["energyplus"] = str(ep_exe) if ep_exe else None
    rep["oshpxml"] = str(osh) if osh else None
    if os_exe:
        try:
            rep["openstudio_version"] = subprocess.run(
                [str(os_exe), "--version"], capture_output=True, text=True, timeout=120
            ).stdout.strip()
        except Exception as e:  # noqa: BLE001
            rep["openstudio_version"] = f"error: {e}"
    if ep_exe:
        try:
            out = subprocess.run([str(ep_exe), "--version"], capture_output=True, text=True, timeout=120)
            rep["energyplus_version"] = (out.stdout or out.stderr).strip()
        except Exception as e:  # noqa: BLE001
            rep["energyplus_version"] = f"error: {e}"
    if osh:
        rep["oshpxml_version"] = OSHPXML_VERSION
    rep["ready"] = bool(os_exe and ep_exe and osh)
    if not rep["ready"]:
        rep["fix"] = "run: uv run scripts/hvacload.py setup   (downloads ~350 MB, no admin rights needed)"
    return rep


def print_json(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))
