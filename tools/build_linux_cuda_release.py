from __future__ import print_function

import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PACKAGE = "bm3dcuda"
VARIANT_VERSIONS = {"cu121": "12.1", "cu129": "12.9"}


def run(command, env):
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=str(ROOT), env=env, check=True)


def nvcc_version(nvcc):
    output = subprocess.check_output([nvcc, "--version"], universal_newlines=True)
    match = re.search(r"release ([0-9]+\.[0-9]+)", output)
    if not match:
        raise RuntimeError("could not determine CUDA version from nvcc: {}".format(output))
    return match.group(1)


def main():
    parser = argparse.ArgumentParser(description="Build a complete Linux BM3DCUDA CUDA Release payload.")
    parser.add_argument("--variant", choices=sorted(VARIANT_VERSIONS), required=True)
    parser.add_argument("--vapoursynth-include", type=Path, required=True)
    parser.add_argument("--cuda-root", type=Path, default=Path("/usr/local/cuda"))
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build-linux-cuda")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cuda_root = args.cuda_root.resolve()
    nvcc = cuda_root / "bin" / "nvcc"
    if not nvcc.is_file():
        raise FileNotFoundError(nvcc)
    expected = VARIANT_VERSIONS[args.variant]
    actual = nvcc_version(str(nvcc))
    if actual != expected:
        raise RuntimeError("{} requires CUDA {}; nvcc reports {}".format(args.variant, expected, actual))

    include_dir = args.vapoursynth_include.resolve()
    if not (include_dir / "VapourSynth4.h").is_file():
        raise FileNotFoundError(include_dir / "VapourSynth4.h")

    cmake = shutil.which("cmake")
    if not cmake:
        raise FileNotFoundError("cmake")
    build_dir = args.build_dir.resolve()
    shutil.rmtree(str(build_dir), ignore_errors=True)
    env = os.environ.copy()
    env["CUDA_PATH"] = str(cuda_root)
    run(
        [
            cmake,
            "-S",
            str(ROOT),
            "-B",
            str(build_dir),
            "-D",
            "CMAKE_BUILD_TYPE=Release",
            "-D",
            "ENABLE_CPU=ON",
            "-D",
            "ENABLE_CUDA=OFF",
            "-D",
            "ENABLE_CUDA_RTC=ON",
            "-D",
            "ENABLE_HIP=OFF",
            "-D",
            "ENABLE_SYCL=OFF",
            "-D",
            "USE_NVRTC_STATIC=ON",
            "-D",
            "VAPOURSYNTH_INCLUDE_DIRECTORY={}".format(include_dir),
            "-D",
            "CUDAToolkit_ROOT={}".format(cuda_root),
        ],
        env,
    )
    run([cmake, "--build", str(build_dir), "--config", "Release"], env)

    def find(name):
        candidates = sorted(build_dir.rglob(name))
        if not candidates:
            raise FileNotFoundError(build_dir / name)
        return candidates[0]

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    package_dir = output.parent / PLUGIN_PACKAGE
    shutil.rmtree(str(package_dir), ignore_errors=True)
    package_dir.mkdir(parents=True)
    shutil.copy2(str(find("bm3dcpu.so")), str(package_dir / "bm3dcpu.so"))
    shutil.copy2(str(find("libbm3dcuda_rtc.so")), str(package_dir / "bm3dcuda_rtc.so"))
    shutil.copy2(str(ROOT / "LICENSE"), str(package_dir / "LICENSE"))
    (package_dir / "manifest.vs").write_text(
        "[VapourSynth Manifest V1]\nbm3dcpu\nbm3dcuda_rtc\n", encoding="ascii"
    )

    if output.exists():
        output.unlink()
    with zipfile.ZipFile(str(output), "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file():
                archive.write(str(path), path.relative_to(output.parent).as_posix())
    print(output)


if __name__ == "__main__":
    main()
