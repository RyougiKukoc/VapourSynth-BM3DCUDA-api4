from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PACKAGE = "bm3dcuda"
CUDA_VARIANTS = {"cu121", "cu129"}
SUPPORTED_VARIANTS = {"cpu", *CUDA_VARIANTS}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Create a BM3DCUDA plugin package zip.")
    parser.add_argument("--input-dir", default=str(ROOT / "dist" / "windows"))
    parser.add_argument("--output", default=str(ROOT / "dist" / "bm3dcuda-cpu-win64.zip"))
    parser.add_argument("--variant", choices=sorted(SUPPORTED_VARIANTS), default="cpu")
    args = parser.parse_args(argv)

    input_dir = Path(args.input_dir).resolve()
    output = Path(args.output).resolve()
    package_dir = input_dir / PLUGIN_PACKAGE
    required = [package_dir / "manifest.vs"]
    forbidden: list[Path] = []
    if args.variant == "cpu":
        required.append(package_dir / "bm3dcpu.dll")
        forbidden.append(package_dir / "bm3dcuda_rtc.dll")
    else:
        required.append(package_dir / "bm3dcuda_rtc.dll")
        forbidden.append(package_dir / "bm3dcpu.dll")

    for path in required:
        if not path.exists():
            raise FileNotFoundError(path)
    for path in forbidden:
        if path.exists():
            raise RuntimeError(f"{args.variant} package unexpectedly contains {path.name}")

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(input_dir))

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
