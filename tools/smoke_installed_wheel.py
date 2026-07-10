from __future__ import annotations

import argparse
import os
import site
import sys
import sysconfig
from pathlib import Path


PLUGIN_PACKAGE = "bm3dcuda"


def add_existing_dll_dirs(paths: list[Path]) -> None:
    for path in paths:
        if path.exists():
            os.add_dll_directory(str(path))


def make_core(vs: object) -> object:
    create_environment = getattr(vs, "create_environment", None)
    if create_environment is not None:
        try:
            env = create_environment()
            return env.get_core()
        except Exception:
            pass

    create_core = getattr(vs, "create_core", None)
    if create_core is not None:
        try:
            return create_core()
        except Exception:
            pass

    core_type = getattr(vs, "Core", None)
    if core_type is not None:
        try:
            return core_type()
        except Exception:
            pass

    return vs.core


def exercise_cpu_filter(core: object, vs: object) -> None:
    clip = core.std.BlankClip(width=16, height=16, length=1, format=vs.YUV444PS, color=[0.5, 0.5, 0.5])
    filtered = core.bm3dcpu.BM3D(clip, sigma=[1.0, 1.0, 1.0], radius=0)
    frame = filtered.get_frame(0)
    stats = core.std.PlaneStats(filtered).get_frame(0).props
    if frame.width != 16 or frame.height != 16:
        raise RuntimeError(f"unexpected output size: {frame.width}x{frame.height}")
    print(f"CPU filter exercise: {frame.format.name} {frame.width}x{frame.height}")
    print(f"PlaneStatsMin={stats['PlaneStatsMin']}")
    print(f"PlaneStatsMax={stats['PlaneStatsMax']}")
    print(f"PlaneStatsAverage={stats['PlaneStatsAverage']}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test an installed vapoursynth-bm3dcuda wheel.")
    parser.add_argument("--expect-rtc", action="store_true", help="Require bm3dcuda_rtc.dll and namespace.")
    parser.add_argument("--exercise-cpu-filter", action="store_true", help="Create a BM3D CPU node and request one frame.")
    args = parser.parse_args(argv)

    try:
        import vapoursynth as vs
    except ImportError as exc:
        print(f"failed to import VapourSynth Python module: {exc}", file=sys.stderr)
        return 1

    vs_pkg = Path(vs.__file__).resolve().parent
    plugin_dir = vs_pkg / "plugins" / PLUGIN_PACKAGE
    required = [
        plugin_dir / "bm3dcpu.dll",
        plugin_dir / "manifest.vs",
    ]
    if args.expect_rtc:
        required.append(plugin_dir / "bm3dcuda_rtc.dll")
    for path in required:
        if not path.exists():
            print(f"missing installed file: {path}", file=sys.stderr)
            return 1

    cuda_path = os.environ.get("CUDA_PATH")
    cuda_dirs = []
    if cuda_path:
        cuda_root = Path(cuda_path)
        cuda_dirs.extend([cuda_root / "bin" / "x64", cuda_root / "bin"])

    add_existing_dll_dirs(
        [
            plugin_dir,
            vs_pkg,
            Path(sys.executable).resolve().parent,
            Path(sysconfig.get_paths().get("platlib", "")),
            Path(sysconfig.get_paths().get("purelib", "")),
            *(Path(p) for p in site.getsitepackages()),
            *cuda_dirs,
        ]
    )

    core = make_core(vs)

    if not hasattr(core, "bm3dcpu") or not hasattr(core.bm3dcpu, "BM3D"):
        print("core.bm3dcpu.BM3D missing after installed-wheel autoload", file=sys.stderr)
        return 1
    if args.expect_rtc and (not hasattr(core, "bm3dcuda_rtc") or not hasattr(core.bm3dcuda_rtc, "BM3D")):
        print("core.bm3dcuda_rtc.BM3D missing after installed-wheel autoload", file=sys.stderr)
        return 1
    print(core.bm3dcpu.BM3D)
    if args.expect_rtc:
        print(core.bm3dcuda_rtc.BM3D)

    if args.exercise_cpu_filter:
        try:
            exercise_cpu_filter(core, vs)
        except Exception as exc:
            print(f"CPU filter exercise failed: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
