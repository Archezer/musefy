"""Build CPU/CUDA release installers and the one-file release checker."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / ".build_tools"
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
MAX_RELEASE_ASSET_BYTES = 1_900_000_000
CHUNK_SIZE = 16 * 1024 * 1024


def _run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def _find_iscc() -> str:
    candidates = (
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Users\4rche\.codex\tools\innosetup\ISCC.exe"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    iscc = shutil.which("ISCC.exe")
    if iscc:
        return iscc
    raise SystemExit("Inno Setup 6 was not found.")


def _prepare_profile(profile: str) -> None:
    environment = os.environ.copy()
    environment["MUSEFY_FORCE_PROFILE"] = profile
    _run(["cmd", "/c", str(ROOT / "install_musefy.bat")], env=environment)


def _build_profile(profile: str) -> Path:
    _prepare_profile(profile)
    environment = os.environ.copy()
    environment["MUSEFY_BUILD_NAME"] = f"Musefy-{profile.upper()}"
    _run([str(VENV_PYTHON), str(ROOT / "scripts" / "build_musefy.py")], env=environment)

    bundle_name = f"Musefy-{profile.upper()}"
    output_name = f"{bundle_name}-Setup"
    _run(
        [
            _find_iscc(),
            f"/DBundleName={bundle_name}",
            f"/DOutputName={output_name}",
            str(ROOT / "installer" / "Musefy.iss"),
        ]
    )
    installer = DIST_DIR / f"{output_name}.exe"
    if not installer.is_file():
        raise SystemExit(f"Expected installer was not created: {installer}")
    return installer


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_assets(installer: Path) -> list[Path]:
    if installer.stat().st_size <= MAX_RELEASE_ASSET_BYTES:
        return [installer]

    part_paths: list[Path] = []
    with installer.open("rb") as source:
        part_number = 1
        while True:
            chunk = source.read(MAX_RELEASE_ASSET_BYTES)
            if not chunk:
                break
            part_path = installer.with_name(
                f"{installer.stem}.part{part_number:02d}"
            )
            part_path.unlink(missing_ok=True)
            part_path.write_bytes(chunk)
            part_paths.append(part_path)
            part_number += 1
    return part_paths


def _manifest_entry(path: Path) -> dict[str, str | int]:
    return {
        "name": path.name,
        "size": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _build_bootstrap(manifest: dict) -> Path:
    manifest_path = BUILD_DIR / "release_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if TOOLS_DIR.is_dir():
        sys.path.insert(0, str(TOOLS_DIR))
    from PyInstaller.__main__ import run as pyinstaller_run

    bootstrap_dist = DIST_DIR
    bootstrap_work = BUILD_DIR / "bootstrap-work"
    bootstrap_spec = BUILD_DIR / "bootstrap-spec"
    pyinstaller_run(
        [
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name",
            "Musefy-Setup",
            "--distpath",
            str(bootstrap_dist),
            "--workpath",
            str(bootstrap_work),
            "--specpath",
            str(bootstrap_spec),
            "--add-data",
            f"{manifest_path}{os.pathsep}.",
            str(ROOT / "scripts" / "release_bootstrap.py"),
        ]
    )
    bootstrap = DIST_DIR / "Musefy-Setup.exe"
    if not bootstrap.is_file():
        raise SystemExit(f"Release checker was not created: {bootstrap}")
    return bootstrap


def main() -> None:
    if not VENV_PYTHON.is_file():
        raise SystemExit(".venv is missing. Run install_musefy.bat first.")

    package_existing = "--package-existing" in sys.argv[1:]
    arguments = [argument for argument in sys.argv[1:] if argument != "--package-existing"]
    tag = arguments[0] if arguments else "v1.0.0"
    if package_existing:
        cpu_installer = DIST_DIR / "Musefy-CPU-Setup.exe"
        cuda_installer = DIST_DIR / "Musefy-CUDA-Setup.exe"
        for installer in (cpu_installer, cuda_installer):
            if not installer.is_file():
                raise SystemExit(f"Existing installer is missing: {installer}")
    else:
        cpu_installer = _build_profile("cpu")
        cuda_installer = _build_profile("cuda")
    cpu_assets = _release_assets(cpu_installer)
    cuda_assets = _release_assets(cuda_installer)

    manifest = {
        "repository": "Archezer/musefy",
        "tag": tag,
        "profiles": {
            "cpu": [_manifest_entry(path) for path in cpu_assets],
            "cuda": [_manifest_entry(path) for path in cuda_assets],
        },
    }
    bootstrap = _build_bootstrap(manifest)

    print("\nRelease assets:")
    for path in [bootstrap, *cpu_assets, *cuda_assets]:
        print(f"  {path.name}: {path.stat().st_size / 1_000_000_000:.2f} GB")
    print("\nSHA256:")
    for path in [bootstrap, *cpu_assets, *cuda_assets]:
        print(f"  {path.name}: {_sha256(path)}")


if __name__ == "__main__":
    main()
