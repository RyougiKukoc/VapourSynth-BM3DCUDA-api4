from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PACKAGE = "bm3dcuda"
CUDA_VARIANTS = {"cu121", "cu129"}
SUPPORTED_VARIANTS = {"cpu", *CUDA_VARIANTS}


def find_vcvars64() -> Path | None:
    for value in ("VCVARS64", "VS_VCVARS64"):
        path_text = os.environ.get(value)
        if path_text and Path(path_text).exists():
            return Path(path_text)

    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat"),
        Path(r"C:\Program Files\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat"),
        Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"),
        Path(r"C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"),
        Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def cl_available(env: dict[str, str]) -> bool:
    return shutil.which("cl.exe", path=env.get("PATH")) is not None or shutil.which("cl", path=env.get("PATH")) is not None


def run_msvc(cmd: list[str], *, env: dict[str, str]) -> None:
    print("+ " + subprocess.list2cmdline(cmd), flush=True)
    if cl_available(env):
        subprocess.run(cmd, cwd=ROOT, env=env, check=True)
        return

    vcvars = find_vcvars64()
    if vcvars is None:
        raise FileNotFoundError("cl.exe is not on PATH and vcvars64.bat was not found")
    command = f'call "{vcvars}" && {subprocess.list2cmdline(cmd)}'
    subprocess.run(command, cwd=ROOT, env=env, shell=True, check=True)


def resolve_vs_include(vapoursynth_root: Path | None) -> Path:
    candidates: list[Path] = []
    if vapoursynth_root:
        root = vapoursynth_root.resolve()
        candidates.extend(
            [
                root / "vapoursynth" / "include",
                root / "sdk" / "include",
                root / "sdk" / "include" / "vapoursynth",
                root / "include",
            ]
        )
    candidates.extend(
        [
            ROOT / "_deps" / "vapoursynth-wheel-R77" / "vapoursynth" / "include",
            Path(r"F:\vpy-api4\external\vapoursynth-R77\include"),
        ]
    )
    for candidate in candidates:
        if (candidate / "VapourSynth4.h").exists():
            return candidate
    raise FileNotFoundError("VapourSynth4.h")


def cuda_root_from_variant(variant: str) -> Path:
    env_root = os.environ.get("CUDA_PATH")
    if env_root:
        return Path(env_root)
    version = {"cu121": "v12.1", "cu129": "v12.9"}[variant]
    return Path(r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA") / version


def resolve_cuda_root(candidate: Path) -> Path:
    candidates = [candidate.resolve(), candidate.resolve() / "Library"]
    for root in candidates:
        if (root / "include" / "nvrtc.h").exists():
            return root
    raise FileNotFoundError(candidate / "include" / "nvrtc.h")


def find_built_dll(build_dir: Path, name: str) -> Path:
    matches = sorted(build_dir.rglob(name))
    if matches:
        return matches[0]
    raise FileNotFoundError(build_dir / name)


def write_manifest(package_dir: Path) -> None:
    plugins = []
    if (package_dir / "bm3dcpu.dll").exists():
        plugins.append("bm3dcpu")
    if (package_dir / "bm3dcuda_rtc.dll").exists():
        plugins.append("bm3dcuda_rtc")
    if not plugins:
        raise FileNotFoundError("no BM3D plugin DLLs staged")
    (package_dir / "manifest.vs").write_text(
        "[VapourSynth Manifest V1]\n" + "\n".join(plugins) + "\n",
        encoding="ascii",
        newline="\n",
    )


def stage_package(build_dir: Path, package_parent: Path, variant: str, *, merge: bool) -> Path:
    package_dir = package_parent / PLUGIN_PACKAGE
    if package_dir.exists() and not merge:
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)

    if variant == "cpu":
        shutil.copy2(find_built_dll(build_dir, "bm3dcpu.dll"), package_dir / "bm3dcpu.dll")
    elif variant in CUDA_VARIANTS:
        shutil.copy2(find_built_dll(build_dir, "bm3dcuda_rtc.dll"), package_dir / "bm3dcuda_rtc.dll")
    else:
        raise RuntimeError(f"unsupported variant {variant}")

    shutil.copy2(ROOT / "LICENSE", package_dir / "LICENSE")
    write_manifest(package_dir)
    return package_dir


def configure_and_build(build_dir: Path, vs_include: Path, extra: list[str], env: dict[str, str]) -> None:
    configure = [
        "cmake",
        "-S",
        str(ROOT),
        "-B",
        str(build_dir),
        "-G",
        "Ninja",
        "-D",
        "CMAKE_BUILD_TYPE=Release",
        "-D",
        f"VAPOURSYNTH_INCLUDE_DIRECTORY={vs_include}",
        "-D",
        "ENABLE_HIP=OFF",
        "-D",
        "ENABLE_SYCL=OFF",
        "-D",
        "CMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded",
        *extra,
    ]
    run_msvc(configure, env=env)
    run_msvc(["cmake", "--build", str(build_dir), "--verbose"], env=env)


def build_cpu(build_dir: Path, vs_include: Path, env: dict[str, str]) -> None:
    configure_and_build(
        build_dir,
        vs_include,
        [
            "-D",
            "ENABLE_CPU=ON",
            "-D",
            "ENABLE_CUDA=OFF",
            "-D",
            "ENABLE_CUDA_RTC=OFF",
            "-D",
            "CMAKE_CXX_FLAGS=/fp:fast /EHsc",
        ],
        env,
    )


def build_cuda_rtc(build_dir: Path, vs_include: Path, cuda_root: Path, env: dict[str, str]) -> None:
    env = env.copy()
    env["CUDA_PATH"] = str(cuda_root)
    cuda_bin = cuda_root / "bin"
    cuda_bin_x64 = cuda_bin / "x64"
    path_entries = [str(path) for path in (cuda_bin_x64, cuda_bin) if path.exists()]
    if path_entries:
        env["PATH"] = os.pathsep.join(path_entries + [env.get("PATH", "")])

    configure_and_build(
        build_dir,
        vs_include,
        [
            "-D",
            "ENABLE_CPU=OFF",
            "-D",
            "ENABLE_CUDA=OFF",
            "-D",
            "ENABLE_CUDA_RTC=ON",
            "-D",
            "USE_NVRTC_STATIC=ON",
            "-D",
            f"CUDAToolkit_ROOT={cuda_root}",
            "-D",
            "CMAKE_CXX_FLAGS=/fp:fast /EHsc",
        ],
        env,
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build a BM3DCUDA Windows package variant with MSVC.")
    default_variant = os.environ.get("BM3DCUDA_VARIANT") or os.environ.get("BM3DCUDA_CUDA_VARIANT") or "cpu"
    parser.add_argument("--variant", choices=sorted(SUPPORTED_VARIANTS), default=default_variant)
    parser.add_argument("--build-dir", default=str(ROOT / "build-windows"))
    parser.add_argument("--dist-dir", default=str(ROOT / "dist" / "windows"))
    parser.add_argument("--vapoursynth-root", help="Extracted VapourSynth wheel root or portable root.")
    parser.add_argument("--cuda-root", help="CUDA toolkit root for cu121/cu129 variants.")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--merge", action="store_true", help="Merge this variant into an existing package directory.")
    args = parser.parse_args(argv)

    variant = args.variant
    build_dir = Path(args.build_dir).resolve()
    dist_dir = Path(args.dist_dir).resolve()
    if args.clean:
        shutil.rmtree(build_dir, ignore_errors=True)
        if not args.merge:
            shutil.rmtree(dist_dir / PLUGIN_PACKAGE, ignore_errors=True)

    vs_include = resolve_vs_include(Path(args.vapoursynth_root) if args.vapoursynth_root else None)
    env = os.environ.copy()

    if variant == "cpu":
        build_cpu(build_dir / "cpu", vs_include, env)
    else:
        cuda_root = resolve_cuda_root(Path(args.cuda_root) if args.cuda_root else cuda_root_from_variant(variant))
        build_cuda_rtc(build_dir / variant, vs_include, cuda_root, env)

    package_dir = stage_package(build_dir, dist_dir, variant, merge=args.merge)
    print(f"Packaged {package_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
