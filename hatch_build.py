from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from packaging import tags


ROOT = Path(__file__).resolve().parent
PLUGIN_PACKAGE = "bm3dcuda"
DEFAULT_REPOSITORY = "RyougiKukoc/VapourSynth-BM3DCUDA-api4"
CUDA_VARIANTS = {"cu121", "cu129"}
SUPPORTED_VARIANTS = {"cpu", *CUDA_VARIANTS}


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() not in {"", "0", "false", "no", "off"})


def _run_text(cmd: list[str]) -> str:
    try:
        result = subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True)
    except Exception:
        return ""
    return result.stdout.strip()


def _repository_from_remote(remote: str) -> str | None:
    remote = remote.strip()
    patterns = [
        r"^https://github\.com/(?P<repo>[^/]+/[^/]+?)(?:\.git)?/?$",
        r"^git@github\.com:(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, remote)
        if match:
            return match.group("repo")
    return None


def _default_repository() -> str:
    override = os.environ.get("BM3DCUDA_PREBUILT_REPOSITORY")
    if override:
        return override
    github_repository = os.environ.get("GITHUB_REPOSITORY")
    if github_repository:
        return github_repository
    remote = _run_text(["git", "config", "--get", "remote.origin.url"])
    parsed = _repository_from_remote(remote)
    return parsed or DEFAULT_REPOSITORY


def _variant_from_environment() -> str | None:
    for name in ("BM3DCUDA_VARIANT", "BM3DCUDA_CUDA_VARIANT", "GITHUB_REF_NAME"):
        value = os.environ.get(name)
        if value in SUPPORTED_VARIANTS:
            return value
    tag = os.environ.get("BM3DCUDA_PREBUILT_TAG")
    if tag in SUPPORTED_VARIANTS:
        return tag
    return None


def _variant_from_git() -> str | None:
    tags_at_head = _run_text(["git", "tag", "--points-at", "HEAD"])
    matches = [tag for tag in tags_at_head.splitlines() if tag in SUPPORTED_VARIANTS]
    if matches:
        return sorted(matches)[0]

    described = _run_text(["git", "describe", "--tags", "--exact-match"])
    if described in SUPPORTED_VARIANTS:
        return described
    return None


def _selected_variant() -> str:
    variant = _variant_from_environment() or _variant_from_git() or "cpu"
    if variant not in SUPPORTED_VARIANTS:
        raise RuntimeError(f"unsupported BM3DCUDA variant {variant!r}; expected one of {sorted(SUPPORTED_VARIANTS)}")
    return variant


def _asset_name(variant: str) -> str:
    return f"{PLUGIN_PACKAGE}-{variant}-win64.zip"


def _default_prebuilt_url(variant: str, *, component: str) -> str:
    repository = _default_repository()
    if component == "cpu":
        tag = os.environ.get("BM3DCUDA_CPU_PREBUILT_TAG") or "cpu"
        asset = os.environ.get("BM3DCUDA_CPU_PREBUILT_ASSET_NAME") or _asset_name("cpu")
    else:
        tag = os.environ.get("BM3DCUDA_CUDA_PREBUILT_TAG") or os.environ.get("BM3DCUDA_PREBUILT_TAG") or variant
        asset = os.environ.get("BM3DCUDA_CUDA_PREBUILT_ASSET_NAME") or os.environ.get("BM3DCUDA_PREBUILT_ASSET_NAME") or _asset_name(variant)
    return f"https://github.com/{repository}/releases/download/{tag}/{asset}"


def _prebuilt_source(variant: str, *, component: str) -> tuple[str, bool]:
    if component == "cpu":
        explicit = os.environ.get("BM3DCUDA_CPU_PREBUILT_URL")
        if explicit:
            return explicit, True
        if variant == "cpu":
            explicit = os.environ.get("BM3DCUDA_PREBUILT_URL")
            if explicit:
                return explicit, True
    else:
        explicit = os.environ.get("BM3DCUDA_CUDA_PREBUILT_URL") or os.environ.get("BM3DCUDA_PREBUILT_URL")
        if explicit:
            return explicit, True
    return _default_prebuilt_url(variant, component=component), False


def _supports_prebuilt() -> bool:
    return sys.platform == "win32" and platform.machine().lower() in {"amd64", "x86_64"}


def _fetch_prebuilt_archive(source: str, destination: Path) -> None:
    candidate = Path(source)
    if candidate.exists():
        shutil.copy2(candidate, destination)
        return

    request = urllib.request.Request(source, headers={"User-Agent": "vapoursynth-bm3dcuda-build-hook"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def _stage_package_from_zip(archive_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(archive_path) as zf:
        package_members = [
            name
            for name in zf.namelist()
            if name.replace("\\", "/").startswith(f"{PLUGIN_PACKAGE}/") and not name.endswith("/")
        ]
        if not package_members:
            raise FileNotFoundError(f"prebuilt archive does not contain a {PLUGIN_PACKAGE}/ package directory")

        for member in package_members:
            normalized = member.replace("\\", "/")
            relative = normalized.split("/", 1)[1]
            out_path = target_dir / relative
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, out_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def _write_merged_manifest(target_dir: Path) -> None:
    plugins = []
    if (target_dir / "bm3dcpu.dll").exists():
        plugins.append("bm3dcpu")
    if (target_dir / "bm3dcuda_rtc.dll").exists():
        plugins.append("bm3dcuda_rtc")
    if not plugins:
        raise FileNotFoundError("no BM3D plugin DLLs were staged")
    (target_dir / "manifest.vs").write_text(
        "[VapourSynth Manifest V1]\n" + "\n".join(plugins) + "\n",
        encoding="ascii",
        newline="\n",
    )


def _validate_staged_package(target_dir: Path, variant: str) -> None:
    required = [target_dir / "bm3dcpu.dll"]
    if variant in CUDA_VARIANTS:
        required.append(target_dir / "bm3dcuda_rtc.dll")
    for path in required:
        if not path.exists():
            raise FileNotFoundError(f"staged package did not provide {path.name}")
    if variant == "cpu" and (target_dir / "bm3dcuda_rtc.dll").exists():
        raise RuntimeError("cpu wheel unexpectedly contains bm3dcuda_rtc.dll")
    _write_merged_manifest(target_dir)


def _stage_prebuilt_plugin(variant: str, target_dir: Path) -> bool:
    if _truthy(os.environ.get("BM3DCUDA_FORCE_BUILD")):
        print("BM3DCUDA wheel build: skipping prebuilt assets because BM3DCUDA_FORCE_BUILD is set")
        return False
    if not _supports_prebuilt():
        print("BM3DCUDA wheel build: prebuilt release asset path only applies to Windows x86_64; falling back to local build")
        return False

    components = ["cpu"] if variant == "cpu" else ["cpu", "cuda"]
    sources = [(component, *_prebuilt_source(variant, component=component)) for component in components]
    try:
        with tempfile.TemporaryDirectory(prefix="bm3dcuda-prebuilt-") as temp_dir_text:
            temp_dir = Path(temp_dir_text)
            for component, source, _explicit in sources:
                archive_path = temp_dir / (Path(source).name or _asset_name("cpu" if component == "cpu" else variant))
                _fetch_prebuilt_archive(source, archive_path)
                _stage_package_from_zip(archive_path, target_dir)
            _validate_staged_package(target_dir, variant)
    except Exception as exc:
        explicit = any(item[2] for item in sources)
        if explicit:
            joined = ", ".join(source for _component, source, _explicit in sources)
            raise RuntimeError(f"failed to use explicit BM3DCUDA prebuilt asset(s): {joined}") from exc
        print(f"BM3DCUDA wheel build: prebuilt assets unavailable; falling back to local build ({exc})")
        return False

    joined = ", ".join(source for _component, source, _explicit in sources)
    print(f"BM3DCUDA wheel build: using {variant} prebuilt release asset(s): {joined}")
    return True


def _run(cmd: list[str], *, env: dict[str, str]) -> None:
    print("+ " + subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True, env=env)


def _stage_local_build(variant: str, target_dir: Path) -> None:
    env = os.environ.copy()
    build_dir = ROOT / f"build-wheel-{variant}"
    plugins_root = target_dir.parent
    _run([sys.executable, "tools/ci_prepare_windows.py"], env=env)
    _run(
        [
            sys.executable,
            "tools/ci_build_windows.py",
            "--clean",
            "--variant",
            "cpu",
            "--build-dir",
            str(build_dir / "cpu"),
            "--dist-dir",
            str(plugins_root),
        ],
        env=env,
    )
    if variant in CUDA_VARIANTS:
        _run(
            [
                sys.executable,
                "tools/ci_build_windows.py",
                "--variant",
                variant,
                "--build-dir",
                str(build_dir / variant),
                "--dist-dir",
                str(plugins_root),
                "--merge",
            ],
            env=env,
        )
    _validate_staged_package(target_dir, variant)


class CustomHook(BuildHookInterface[Any]):
    build_dir = ROOT / "build-wheel"
    dist_dir = ROOT / "vapoursynth" / "plugins" / PLUGIN_PACKAGE

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        del version
        build_data["pure_python"] = False
        build_data["tag"] = f"py3-none-{next(tags.platform_tags())}"
        variant = _selected_variant()

        shutil.rmtree(self.build_dir, ignore_errors=True)
        shutil.rmtree(self.dist_dir.parent.parent, ignore_errors=True)
        self.dist_dir.mkdir(parents=True, exist_ok=True)

        if not _stage_prebuilt_plugin(variant, self.dist_dir):
            _stage_local_build(variant, self.dist_dir)

    def finalize(self, version: str, build_data: dict[str, Any], artifact_path: str) -> None:
        del version, build_data, artifact_path
        shutil.rmtree(self.build_dir, ignore_errors=True)
        shutil.rmtree(self.dist_dir.parent.parent, ignore_errors=True)
