"""Build, verify and zip a Windows portable folder using the active environment."""
from __future__ import annotations

import hashlib
from importlib import metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Build the Windows release on Windows.")
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-q"], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "packaging/AirControl.spec"],
                   cwd=ROOT, check=True)
    bundle = ROOT / "dist" / "AirControl"
    for name in ("requirements.txt", "requirements-lock.txt"):
        shutil.copy2(ROOT / name, bundle / name)
    shutil.copy2(ROOT / "docs" / "USER_GUIDE.md", bundle / "USER_GUIDE.md")
    (bundle / "Start AirControl.cmd").write_text(
        '@echo off\ncd /d "%~dp0"\nAirControl.exe %*\nif errorlevel 1 pause\n', encoding="ascii")
    notices = bundle / "third_party_licenses"
    notices.mkdir(exist_ok=True)
    python_license = Path(sys.base_prefix) / "LICENSE_PYTHON.txt"
    if not python_license.is_file():
        raise FileNotFoundError(f"Python license not found: {python_license}")
    shutil.copy2(python_license, notices / "LICENSE_PYTHON.txt")
    records = []
    for dist in sorted(metadata.distributions(), key=lambda item: item.metadata["Name"].lower()):
        name = dist.metadata["Name"]
        copied = []
        for file in dist.files or ():
            # Preserve the license/notice files distributed by installed packages.
            if any(token in str(file).lower() for token in ("license", "licence", "notice", "copying")):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    target = notices / name / str(file).replace("..", "__")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    copied.append(str(target.relative_to(bundle)))
        records.append(f"{name}=={dist.version}: " + (", ".join(copied) or "No license file supplied in this installation; see package metadata."))
    (bundle / "THIRD_PARTY_NOTICES.txt").write_text(
        "AirControl Windows portable build\n"
        "Python license: third_party_licenses/LICENSE_PYTHON.txt\n"
        "This inventory includes installed runtime and build packages. It is not a license grant.\n"
        "Hand Landmarker model source and SHA256: _internal/models/README.md\n"
        "Model documentation: https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker\n\n"
        + "\n".join(records) + "\n", encoding="utf-8")
    (bundle / "BUILD_INFO.txt").write_text(
        f"Python: {sys.version}\nPlatform: {sys.platform}\n"
        f"PyInstaller: {metadata.version('pyinstaller')}\n"
        f"Hooks: {metadata.version('pyinstaller-hooks-contrib')}\n"
        "Default: Scheme B preview; C or --control enables real input.\n", encoding="utf-8")
    # A different cwd catches accidental reliance on the source checkout.
    check_env = os.environ.copy()
    for key in ("PYTHONHOME", "PYTHONPATH"):
        check_env.pop(key, None)
    windows = Path(check_env.get("SystemRoot", r"C:\Windows"))
    check_env["PATH"] = os.pathsep.join((str(windows / "System32"), str(windows)))
    with tempfile.TemporaryDirectory(prefix="aircontrol-check-") as check_dir:
        subprocess.run([str(bundle / "AirControl.exe"), "--self-check"],
                       cwd=check_dir, env=check_env, check=True, timeout=120)
    releases = ROOT / "releases"
    releases.mkdir(exist_ok=True)
    archive = releases / "AirControl-v0.1.0-windows-x64.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for file in sorted(bundle.rglob("*")):
            if file.is_file():
                output.write(file, file.relative_to(bundle.parent))
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(f"Release: {archive}\nSHA256: {digest}", flush=True)


if __name__ == "__main__":
    main()
