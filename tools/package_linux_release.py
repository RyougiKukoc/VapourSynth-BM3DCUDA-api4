from __future__ import annotations

import argparse
import shutil
import tempfile
import zipfile
from pathlib import Path


PLUGIN_PACKAGE = "bm3dcuda"
CUDA_VARIANTS = {"cu121", "cu129"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a BM3DCUDA Linux Release payload from a wheel.")
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--variant", choices=["cpu", *sorted(CUDA_VARIANTS)], default="cpu")
    args = parser.parse_args()

    wheel = args.wheel.resolve()
    output = args.output.resolve()
    if not wheel.is_file():
        raise FileNotFoundError(wheel)

    with tempfile.TemporaryDirectory(prefix="bm3dcuda-linux-release-") as temp_text:
        temp_dir = Path(temp_text)
        with zipfile.ZipFile(wheel) as source:
            members = [
                member
                for member in source.namelist()
                if member.startswith(f"vapoursynth/plugins/{PLUGIN_PACKAGE}/") and not member.endswith("/")
            ]
            if not members:
                raise FileNotFoundError(f"{wheel} does not contain vapoursynth/plugins/{PLUGIN_PACKAGE}/")
            for member in members:
                relative = Path(member).relative_to("vapoursynth/plugins")
                destination = temp_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as src, destination.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

        package_dir = temp_dir / PLUGIN_PACKAGE
        required = [package_dir / "manifest.vs", package_dir / "bm3dcpu.so", package_dir / "LICENSE"]
        if args.variant in CUDA_VARIANTS:
            required.append(package_dir / "bm3dcuda_rtc.so")
        for path in required:
            if not path.is_file():
                raise FileNotFoundError(path)
        if args.variant == "cpu" and (package_dir / "bm3dcuda_rtc.so").exists():
            raise RuntimeError("CPU Linux payload unexpectedly contains bm3dcuda_rtc.so")

        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            output.unlink()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as destination:
            for path in sorted(package_dir.rglob("*")):
                if path.is_file():
                    destination.write(path, path.relative_to(temp_dir).as_posix())

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
