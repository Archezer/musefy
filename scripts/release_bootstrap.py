"""Download and launch the correct Musefy release installer.

This tiny GUI is the only file a normal user needs to download.  The release
manifest is embedded into the PyInstaller executable by build_release.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from tkinter import Tk, messagebox, ttk

CHUNK_SIZE = 8 * 1024 * 1024


def _resource_path(name: str) -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / name


def _load_manifest() -> dict:
    manifest_path = _resource_path("release_manifest.json")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _cuda_driver_available() -> bool:
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=8,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


class DownloadWindow:
    def __init__(self, root: Tk, total_bytes: int) -> None:
        self.root = root
        self.total_bytes = total_bytes
        self.downloaded_bytes = 0
        self.label = ttk.Label(root, text="Подготовка загрузки...")
        self.label.pack(padx=24, pady=(22, 8))
        self.progress = ttk.Progressbar(root, length=420, mode="determinate")
        self.progress.pack(padx=24, pady=(0, 22))
        self.root.title("Musefy")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._disable_close)

    def _disable_close(self) -> None:
        messagebox.showinfo(
            "Musefy",
            "Загрузка ещё выполняется. Дождитесь её завершения.",
            parent=self.root,
        )

    def update(self, filename: str, downloaded: int) -> None:
        self.downloaded_bytes += downloaded
        self.label.configure(text=f"Загрузка: {filename}")
        if self.total_bytes:
            self.progress["value"] = self.downloaded_bytes / self.total_bytes * 100
        self.root.update_idletasks()


def _download_asset(
    window: DownloadWindow,
    url: str,
    destination: Path,
    expected_size: int,
    expected_sha256: str,
) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Musefy-Setup"})
    digest = hashlib.sha256()
    actual_size = 0
    try:
        with urllib.request.urlopen(request, timeout=60) as response, destination.open(
            "wb"
        ) as output:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    actual_size += len(chunk)
                    window.update(destination.name, len(chunk))
    except (urllib.error.URLError, OSError) as error:
        raise RuntimeError(f"Не удалось скачать {destination.name}: {error}") from error

    if actual_size != expected_size:
        raise RuntimeError(
            f"Размер {destination.name} не совпадает: {actual_size} вместо {expected_size}."
        )
    if digest.hexdigest().lower() != expected_sha256.lower():
        raise RuntimeError(f"Проверка целостности {destination.name} не пройдена.")


def _assemble_installer(
    window: DownloadWindow,
    manifest: dict,
    profile: str,
    temporary_dir: Path,
) -> Path:
    repository = manifest["repository"]
    tag = manifest["tag"]
    assets = manifest["profiles"][profile]
    downloaded_paths: list[Path] = []

    for asset in assets:
        filename = asset["name"]
        url = (
            f"https://github.com/{repository}/releases/download/"
            f"{urllib.parse.quote(tag, safe='')}/{urllib.parse.quote(filename, safe='')}"
        )
        destination = temporary_dir / filename
        _download_asset(
            window,
            url,
            destination,
            int(asset["size"]),
            asset["sha256"],
        )
        downloaded_paths.append(destination)

    if len(downloaded_paths) == 1:
        return downloaded_paths[0]

    installer_path = temporary_dir / f"Musefy-{profile.upper()}-Setup.exe"
    with installer_path.open("wb") as output:
        for part_path in downloaded_paths:
            with part_path.open("rb") as part:
                shutil.copyfileobj(part, output, length=CHUNK_SIZE)
    for part_path in downloaded_paths:
        part_path.unlink()
    expected_total = sum(int(asset["size"]) for asset in assets)
    if installer_path.stat().st_size != expected_total:
        raise RuntimeError("Собранный установщик имеет неправильный размер.")
    return installer_path


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--cuda", action="store_true")
    options, _ = parser.parse_known_args()
    if options.cpu and options.cuda:
        raise SystemExit("Use only one of --cpu or --cuda.")

    root = Tk()
    root_destroyed = False
    root.withdraw()
    try:
        manifest = _load_manifest()
        if options.cuda:
            profile = "cuda"
        elif options.cpu:
            profile = "cpu"
        else:
            profile = "cuda" if _cuda_driver_available() else "cpu"

        profile_title = "CUDA" if profile == "cuda" else "CPU"
        if not messagebox.askyesno(
            "Musefy",
            f"Выбрана версия {profile_title}.\n\n"
            "Установщик скачает необходимые файлы из GitHub Releases.\n"
            "Продолжить?",
            parent=root,
        ):
            return 0

        assets = manifest["profiles"][profile]
        total_bytes = sum(int(asset["size"]) for asset in assets)
        root.deiconify()
        window = DownloadWindow(root, total_bytes)
        temporary_dir = Path(tempfile.mkdtemp(prefix="musefy-setup-"))
        try:
            installer_path = _assemble_installer(window, manifest, profile, temporary_dir)
            root.destroy()
            root_destroyed = True
            process = subprocess.Popen([str(installer_path)])
            process.wait()
        finally:
            shutil.rmtree(temporary_dir, ignore_errors=True)
    except Exception as error:  # noqa: BLE001 - show all setup failures to the user.
        if not root_destroyed:
            root.destroy()
        messagebox.showerror("Musefy", str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
