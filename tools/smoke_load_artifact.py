from __future__ import annotations

import argparse
import os
import site
import sys
import sysconfig
from pathlib import Path


PLUGIN_PACKAGE = "bm3dcuda"


def resolve_vapoursynth_paths(root: Path | None) -> tuple[list[Path], list[Path]]:
    if root is None:
        return [], []

    root = root.resolve()
    candidates = [
        (root, root / "vapoursynth"),
        (root / "Lib" / "site-packages", root / "Lib" / "site-packages" / "vapoursynth"),
        (root.parent, root),
    ]
    for sys_path, dll_path in candidates:
        if (dll_path / "libvapoursynth.dll").exists() and (dll_path / "__init__.py").exists():
            return [sys_path], [dll_path]
    return [root], [root]


def resolve_artifact(root: Path) -> Path:
    root = root.resolve()
    candidates = [
        root,
        root / PLUGIN_PACKAGE,
        root / "vapoursynth" / "plugins" / PLUGIN_PACKAGE,
    ]
    for candidate in candidates:
        if (candidate / "manifest.vs").exists() and (
            (candidate / "bm3dcpu.dll").exists() or (candidate / "bm3dcuda_rtc.dll").exists()
        ):
            return candidate
    raise FileNotFoundError(root / PLUGIN_PACKAGE / "manifest.vs")


def add_existing_dll_dirs(paths: list[Path]) -> None:
    for path in paths:
        if path.exists():
            os.add_dll_directory(str(path))


def has_filter(core: object, namespace: str, function: str) -> bool:
    return hasattr(core, namespace) and hasattr(getattr(core, namespace), function)


def make_core(vs: object, *, autoload: bool) -> object:
    flags = 0 if autoload else vs.DISABLE_AUTO_LOADING
    create_environment = getattr(vs, "create_environment", None)
    if create_environment is not None:
        for factory in (
            lambda: create_environment(flags=flags),
            lambda: create_environment(flags),
        ):
            try:
                env = factory()
                return env.get_core()
            except Exception:
                continue

    create_core = getattr(vs, "create_core", None)
    if create_core is not None:
        for factory in (
            lambda: create_core(flags=flags),
            lambda: create_core(flags),
        ):
            try:
                return factory()
            except Exception:
                continue

    core_type = getattr(vs, "Core", None)
    if core_type is not None:
        for factory in (
            lambda: core_type(flags=flags),
            lambda: core_type(flags),
            lambda: core_type(),
        ):
            try:
                return factory()
            except Exception:
                continue

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
    parser = argparse.ArgumentParser(description="Smoke-load a built BM3DCUDA artifact with VapourSynth.")
    parser.add_argument("--vapoursynth-root", help="VapourSynth portable root or extracted wheel root.")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--autoload", action="store_true", help="Load through VAPOURSYNTH_EXTRA_PLUGIN_PATH instead of std.LoadPlugin.")
    parser.add_argument("--exercise-cpu-filter", action="store_true", help="Create a BM3D CPU node and request one frame.")
    args = parser.parse_args(argv)

    vs_root = Path(args.vapoursynth_root).resolve() if args.vapoursynth_root else None
    artifact_root = Path(args.artifact_dir).resolve()
    artifact = resolve_artifact(artifact_root)

    sys_paths, dll_paths = resolve_vapoursynth_paths(vs_root)
    for path in reversed(sys_paths):
        if path.exists():
            sys.path.insert(0, str(path))

    cuda_path = os.environ.get("CUDA_PATH")
    cuda_dirs = []
    if cuda_path:
        cuda_root = Path(cuda_path)
        cuda_dirs.extend([cuda_root / "bin" / "x64", cuda_root / "bin"])

    add_existing_dll_dirs(
        [
            artifact,
            Path(sys.executable).resolve().parent,
            Path(sysconfig.get_paths().get("platlib", "")),
            Path(sysconfig.get_paths().get("purelib", "")),
            *(Path(p) for p in site.getsitepackages()),
            *dll_paths,
            *cuda_dirs,
        ]
    )

    if args.autoload:
        os.environ["VAPOURSYNTH_EXTRA_PLUGIN_PATH"] = str(artifact.parent)

    try:
        import vapoursynth as vs
    except ImportError as exc:
        print(f"failed to import VapourSynth Python module: {exc}", file=sys.stderr)
        return 1

    core = make_core(vs, autoload=args.autoload)

    has_cpu = (artifact / "bm3dcpu.dll").exists()
    has_rtc = (artifact / "bm3dcuda_rtc.dll").exists()
    if not args.autoload:
        if has_cpu:
            core.std.LoadPlugin(str(artifact / "bm3dcpu.dll"))
        if has_rtc:
            core.std.LoadPlugin(str(artifact / "bm3dcuda_rtc.dll"))

    missing = []
    if has_cpu and not has_filter(core, "bm3dcpu", "BM3D"):
        missing.append("bm3dcpu.BM3D")
    if has_rtc and not has_filter(core, "bm3dcuda_rtc", "BM3D"):
        missing.append("bm3dcuda_rtc.BM3D")
    if missing:
        print(f"missing plugin functions after loading artifact: {missing}", file=sys.stderr)
        return 1

    if has_cpu:
        print(core.bm3dcpu.BM3D)
    if has_rtc:
        print(core.bm3dcuda_rtc.BM3D)

    if args.exercise_cpu_filter:
        if not has_cpu:
            print("cannot exercise CPU filter: artifact does not contain bm3dcpu.dll", file=sys.stderr)
            return 1
        try:
            exercise_cpu_filter(core, vs)
        except Exception as exc:
            print(f"CPU filter exercise failed: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
