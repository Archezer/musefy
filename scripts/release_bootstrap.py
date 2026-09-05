"""Check the local GPU and open the matching Musefy release downloads.

The resulting ``Musefy-Setup.exe`` is intentionally only a small checker. It
does not download, unpack, or launch another executable. This keeps the
user-visible bootstrapper simple: the user chooses and downloads the release
asset directly from GitHub in their browser.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
import webbrowser
from pathlib import Path
from tkinter import Tk, messagebox, ttk


def _resource_path(name: str) -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / name


def _load_manifest() -> dict:
    manifest_path = _resource_path("release_manifest.json")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _cuda_driver_available() -> bool:
    """Return whether an NVIDIA driver responds to ``nvidia-smi``.

    This deliberately checks the driver/GPU only. A separate CUDA Toolkit is
    not required by the packaged application.
    """

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


def _release_url(manifest: dict) -> str:
    repository = manifest["repository"]
    tag = urllib.parse.quote(str(manifest["tag"]), safe="")
    return f"https://github.com/{repository}/releases/tag/{tag}"


def _asset_url(manifest: dict, asset_name: str) -> str:
    repository = manifest["repository"]
    tag = urllib.parse.quote(str(manifest["tag"]), safe="")
    filename = urllib.parse.quote(asset_name, safe="")
    return (
        f"https://github.com/{repository}/releases/download/{tag}/{filename}"
    )


def _format_size(size: int) -> str:
    if size >= 1_000_000_000:
        return f"{size / 1_000_000_000:.2f} ГБ"
    return f"{size / 1_000_000:.0f} МБ"


def _profile_assets(manifest: dict, profile: str) -> list[dict]:
    return list(manifest["profiles"][profile])


class CheckerWindow:
    def __init__(self, root: Tk, manifest: dict, detected_cuda: bool, profile: str):
        self.root = root
        self.manifest = manifest
        self.root.title("Musefy — проверка системы")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

        frame = ttk.Frame(root, padding=24)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(
            frame,
            text="Musefy",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            frame,
            text="Проверяем, какую версию приложения лучше установить.",
        ).grid(row=1, column=0, columnspan=2, pady=(4, 16), sticky="w")

        if detected_cuda:
            verdict = "NVIDIA GPU и драйвер обнаружены."
            verdict_detail = (
                "Рекомендуется CUDA-версия; приложение дополнительно проверит CUDA "
                "после установки."
            )
        else:
            verdict = "CUDA не обнаружена: NVIDIA GPU или драйвер не найден."
            verdict_detail = "Рекомендуется CPU-версия приложения."

        ttk.Label(frame, text=verdict, wraplength=500).grid(
            row=2, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(frame, text=verdict_detail).grid(
            row=3, column=0, columnspan=2, pady=(2, 16), sticky="w"
        )

        ttk.Label(
            frame,
            text=(
                "Этот файл ничего не скачивает и не запускает автоматически.\n"
                "Нажмите нужную кнопку: загрузка откроется в браузере с GitHub."
            ),
            wraplength=500,
        ).grid(row=4, column=0, columnspan=2, pady=(0, 16), sticky="w")

        self._add_profile_row(frame, "cpu", 5, profile == "cpu")
        self._add_profile_row(frame, "cuda", 7, profile == "cuda")

        ttk.Button(
            frame,
            text="Открыть страницу релиза",
            command=lambda: self._open_url(_release_url(manifest)),
        ).grid(row=9, column=0, columnspan=2, pady=(18, 0), sticky="ew")

        ttk.Label(
            frame,
            text="После загрузки запустите CPU-установщик. Для CUDA скачайте обе части.",
            wraplength=500,
        ).grid(row=10, column=0, columnspan=2, pady=(10, 0), sticky="w")

    def _add_profile_row(
        self,
        frame: ttk.Frame,
        profile: str,
        row: int,
        recommended: bool,
    ) -> None:
        assets = _profile_assets(self.manifest, profile)
        title = "CPU-версия" if profile == "cpu" else "CUDA-версия"
        if recommended:
            title += " (рекомендуется)"
        details = ", ".join(
            f"{asset['name']} — {_format_size(int(asset['size']))}"
            for asset in assets
        )

        ttk.Label(frame, text=title).grid(row=row, column=0, sticky="w")
        ttk.Button(
            frame,
            text="Скачать",
            command=lambda p=profile: self._open_profile_downloads(p),
        ).grid(row=row, column=1, padx=(16, 0), sticky="e")
        ttk.Label(
            frame,
            text=details,
            foreground="#555555",
            wraplength=390,
        ).grid(row=row + 1, column=0, columnspan=2, pady=(2, 8), sticky="w")

    def _open_profile_downloads(self, profile: str) -> None:
        assets = _profile_assets(self.manifest, profile)
        for asset in assets:
            self._open_url(_asset_url(self.manifest, str(asset["name"])))
        if profile == "cuda" and len(assets) > 1:
            messagebox.showinfo(
                "Musefy",
                "Для CUDA открыты обе части установщика.\n"
                "Сохраните их в одной папке и объедините командой из README:\n\n"
                "copy /b Musefy-CUDA-Setup.part01+Musefy-CUDA-Setup.part02 "
                "Musefy-CUDA-Setup.exe",
                parent=self.root,
            )

    def _open_url(self, url: str) -> None:
        if not webbrowser.open(url):
            messagebox.showerror(
                "Musefy",
                f"Не удалось открыть браузер. Откройте ссылку вручную:\n\n{url}",
                parent=self.root,
            )


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--cuda", action="store_true")
    options, _ = parser.parse_known_args()
    if options.cpu and options.cuda:
        raise SystemExit("Use only one of --cpu or --cuda.")

    root = Tk()
    root.withdraw()
    try:
        manifest = _load_manifest()
        detected_cuda = _cuda_driver_available()
        if options.cuda:
            profile = "cuda"
        elif options.cpu:
            profile = "cpu"
        else:
            profile = "cuda" if detected_cuda else "cpu"
        root.deiconify()
        CheckerWindow(root, manifest, detected_cuda, profile)
        root.mainloop()
    except Exception as error:  # noqa: BLE001 - show setup failures to the user.
        root.destroy()
        messagebox.showerror("Musefy", str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
