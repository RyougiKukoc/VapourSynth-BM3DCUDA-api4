from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any


PLUGIN_PACKAGE = "bm3dcuda"
CPU_PLUGIN = "bm3dcpu.so"
RTC_PLUGIN = "bm3dcuda_rtc.so"
ACTIVE_POLICY: "IsolatedEnvironmentPolicy | None" = None


class IsolatedEnvironmentPolicy:
    def __init__(self, vs: Any, flags: int) -> None:
        self._api: Any = None
        self._environment: Any = None
        self._flags = flags

    def on_policy_registered(self, api: Any) -> None:
        self._api = api
        self._environment = api.create_environment(self._flags)

    def on_policy_cleared(self) -> None:
        self._api = None
        self._environment = None

    def get_current_environment(self) -> Any:
        return self._environment

    def set_environment(self, environment: Any) -> Any:
        previous = self._environment
        if environment is not None:
            self._environment = environment
        return previous

    def is_alive(self, environment: Any) -> bool:
        return environment is self._environment

    def close(self) -> None:
        if self._api is not None and self._environment is not None:
            self._api.destroy_environment(self._environment)
            self._environment = None


def _make_core(vs: Any, *, autoload: bool) -> Any:
    global ACTIVE_POLICY
    flags = 0 if autoload else int(vs.DISABLE_AUTO_LOADING)
    if getattr(vs, "has_policy", lambda: False)():
        raise RuntimeError("cannot create an isolated core after a VapourSynth environment policy is installed")
    if getattr(vs, "EnvironmentPolicy", None) is not None and getattr(vs, "register_policy", None) is not None:
        ACTIVE_POLICY = IsolatedEnvironmentPolicy(vs, flags)
        vs.register_policy(ACTIVE_POLICY)
        return vs.core
    create_environment = getattr(vs, "create_environment", None)
    if create_environment is not None:
        return create_environment(flags=flags).get_core()
    core_type = getattr(vs, "Core", None)
    if core_type is not None:
        return core_type(flags=flags)
    if autoload:
        return vs.core
    raise RuntimeError("VapourSynth binding does not provide an isolated core constructor")


def _validate_package(package_dir: Path, *, expect_rtc: bool) -> None:
    required = [package_dir / "manifest.vs", package_dir / CPU_PLUGIN, package_dir / "LICENSE"]
    if expect_rtc:
        required.append(package_dir / RTC_PLUGIN)
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    if not expect_rtc and (package_dir / RTC_PLUGIN).exists():
        raise RuntimeError("CPU Linux payload unexpectedly contains bm3dcuda_rtc.so")
    manifest = (package_dir / "manifest.vs").read_text(encoding="ascii")
    expected_plugins = ["bm3dcpu", *( ["bm3dcuda_rtc"] if expect_rtc else [])]
    for plugin in expected_plugins:
        if plugin not in manifest:
            raise RuntimeError(f"manifest.vs does not list {plugin}")


def _extract_release(artifact: Path, destination: Path, *, expect_rtc: bool) -> Path:
    with zipfile.ZipFile(artifact) as archive:
        files = [name.replace("\\", "/") for name in archive.namelist() if not name.endswith("/")]
        roots = {name.split("/", 1)[0] for name in files}
        if roots != {PLUGIN_PACKAGE}:
            raise RuntimeError(f"release zip must have exactly one top-level {PLUGIN_PACKAGE}/ directory: {sorted(roots)}")
        for name in files:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as src, target.open("wb") as dst:
                dst.write(src.read())
    package_dir = destination / PLUGIN_PACKAGE
    _validate_package(package_dir, expect_rtc=expect_rtc)
    return package_dir


def _frame_hash(frame: Any) -> str:
    digest = hashlib.sha256()
    for plane in range(frame.format.num_planes):
        digest.update(memoryview(frame[plane]).tobytes())
    return digest.hexdigest()


def _make_input(core: Any, vs: Any) -> Any:
    return core.std.Splice(
        [
            core.std.BlankClip(
                width=64,
                height=48,
                length=1,
                format=vs.YUV444PS,
                color=[0.05 + index * 0.02, 0.25 + index * 0.01, 0.75 - index * 0.01],
            )
            for index in range(12)
        ]
    )


def _report_frames(core: Any, filtered: Any) -> list[dict[str, Any]]:
    frames = []
    for index in (0, 3, 11):
        frame = filtered.get_frame(index)
        stats = []
        for plane in range(frame.format.num_planes):
            props = core.std.PlaneStats(filtered, plane=plane).get_frame(index).props
            stats.append(
                {
                    "min": props["PlaneStatsMin"],
                    "max": props["PlaneStatsMax"],
                    "average": props["PlaneStatsAverage"],
                }
            )
        frames.append(
            {
                "index": index,
                "sha256": _frame_hash(frame),
                "width": frame.width,
                "height": frame.height,
                "format": frame.format.name,
                "plane_stats": stats,
            }
        )
    return frames


def _gpu_details() -> dict[str, Any]:
    details: dict[str, Any] = {}
    try:
        details["nvidia_smi"] = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,compute_cap,driver_version", "--format=csv,noheader"], text=True
        ).strip()
    except Exception as exc:
        details["nvidia_smi_error"] = str(exc)
    try:
        driver = ctypes.CDLL("libcuda.so.1")
        version = ctypes.c_int()
        result = driver.cuDriverGetVersion(ctypes.byref(version))
        details["cuDriverGetVersion"] = version.value if result == 0 else f"error {result}"
    except OSError as exc:
        details["cuDriverGetVersion_error"] = str(exc)
    return details


def _exercise_filters(core: Any, vs: Any, *, expect_rtc: bool) -> dict[str, Any]:
    clip = _make_input(core, vs)
    cpu = core.bm3dcpu.BM3D(clip, sigma=[1.0, 1.0, 1.0], radius=0)
    report: dict[str, Any] = {"cpu": {"frames": _report_frames(core, cpu)}}

    try:
        core.bm3dcpu.BM3D(clip, radius=-1).get_frame(0)
    except Exception as exc:
        report["invalid_radius"] = {"raised": True, "type": type(exc).__name__, "message": str(exc)}
    else:
        raise RuntimeError("BM3D unexpectedly accepted a negative radius")

    if expect_rtc:
        rtc = core.bm3dcuda_rtc.BM3D(
            clip,
            sigma=[1.0, 1.0, 1.0],
            radius=0,
            device_id=0,
            fast=False,
            extractor_exp=3,
        )
        report["cuda_rtc"] = {"frames": _report_frames(core, rtc), "gpu": _gpu_details()}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a Linux BM3DCUDA Release payload.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--artifact-zip", type=Path)
    source.add_argument("--installed", action="store_true")
    parser.add_argument("--expect-rtc", action="store_true", help="Require and execute bm3dcuda_rtc.so on GPU 0.")
    args = parser.parse_args()

    import vapoursynth as vs

    temporary: tempfile.TemporaryDirectory[str] | None = None
    if args.artifact_zip:
        artifact = args.artifact_zip.resolve()
        if not artifact.is_file():
            raise FileNotFoundError(artifact)
        temporary = tempfile.TemporaryDirectory(prefix="bm3dcuda-smoke-")
        package_dir = _extract_release(artifact, Path(temporary.name), expect_rtc=args.expect_rtc)
        core = _make_core(vs, autoload=False)
        core.std.LoadPlugin(str(package_dir / CPU_PLUGIN))
        if args.expect_rtc:
            core.std.LoadPlugin(str(package_dir / RTC_PLUGIN))
        source_name = "release-zip-explicit-load"
    else:
        package_dir = Path(vs.__file__).resolve().parent / "plugins" / PLUGIN_PACKAGE
        _validate_package(package_dir, expect_rtc=args.expect_rtc)
        core = _make_core(vs, autoload=True)
        source_name = "installed-wheel-autoload"

    try:
        required_namespaces = ["bm3dcpu", *( ["bm3dcuda_rtc"] if args.expect_rtc else [])]
        for namespace in required_namespaces:
            if not hasattr(core, namespace) or not hasattr(getattr(core, namespace), "BM3D"):
                raise RuntimeError(f"core.{namespace}.BM3D is unavailable after plugin load")
        report = {
            "source": source_name,
            "plugin_dir": str(package_dir),
            "manifest": (package_dir / "manifest.vs").read_text(encoding="ascii"),
            "vapoursynth": vs.__version__,
            **_exercise_filters(core, vs, expect_rtc=args.expect_rtc),
        }
        print(json.dumps(report, sort_keys=True))
    finally:
        global ACTIVE_POLICY
        if ACTIVE_POLICY is not None:
            ACTIVE_POLICY.close()
            ACTIVE_POLICY = None
        if temporary is not None:
            temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
