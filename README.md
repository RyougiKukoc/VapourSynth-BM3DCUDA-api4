# VapourSynth-BM3DCUDA

Copyright© 2021 WolframRhodium

BM3D denoising filter for VapourSynth API4. This fork publishes only Windows
release-backed VCS packages for the `bm3dcpu` and `bm3dcuda_rtc` plugins.

Current package version: `2.15`.

This fork intentionally does not publish the standard `bm3dcuda`, HIP, or SYCL
backends.

## Description

- Please check [VapourSynth-BM3D](https://github.com/HomeOfVapourSynthEvolution/VapourSynth-BM3D).

- The `_rtc` version compiles GPU code at runtime, which might run faster than the standard version in steady state at the cost of startup compilation overhead.

- The `cpu` version is implemented in AVX and AVX2 intrinsics, serves as a reference implementation on CPU. However, _bitwise identical_ outputs are not guaranteed across CPU and CUDA implementations.

## Published Variants

The repository has three user-facing install tags:

| Tag | Intended user | Installed plugins | Release assets used |
| --- | --- | --- | --- |
| `cpu` | Machines without an NVIDIA GPU, or users who only want the CPU backend. | `bm3dcpu.dll` | `cpu` release: `bm3dcuda-cpu-win64.zip` |
| `cu121` | NVIDIA users whose driver supports CUDA 12.1. | `bm3dcpu.dll` and CUDA 12.1 static-NVRTC `bm3dcuda_rtc.dll` | `cpu` release plus `cu121` release: `bm3dcuda-cu121-win64.zip` |
| `cu129` | NVIDIA users whose driver supports CUDA 12.9. | `bm3dcpu.dll` and CUDA 12.9 static-NVRTC `bm3dcuda_rtc.dll` | `cpu` release plus `cu129` release: `bm3dcuda-cu129-win64.zip` |

The CUDA variants deliberately include the CPU backend as well, so scripts can
use `core.bm3dcpu` and `core.bm3dcuda_rtc` from the same installation. Users
without an NVIDIA GPU should install the `cpu` tag.

## Installation

Install from an explicit tag. The default branch is not the user-facing
installation target.

```powershell
pip install "vapoursynth-bm3dcuda @ git+https://github.com/RyougiKukoc/VapourSynth-BM3DCUDA-api4.git@cpu"
pip install "vapoursynth-bm3dcuda @ git+https://github.com/RyougiKukoc/VapourSynth-BM3DCUDA-api4.git@cu121"
pip install "vapoursynth-bm3dcuda @ git+https://github.com/RyougiKukoc/VapourSynth-BM3DCUDA-api4.git@cu129"
```

If you switch between variants, force a reinstall so pip replaces the existing
wheel:

```powershell
pip install --force-reinstall "vapoursynth-bm3dcuda @ git+https://github.com/RyougiKukoc/VapourSynth-BM3DCUDA-api4.git@cu121"
```

The build hook downloads the matching GitHub Release assets and places the
plugin package under VapourSynth's autoload tree:

```text
vapoursynth/plugins/bm3dcuda/
  manifest.vs
  bm3dcpu.dll
  bm3dcuda_rtc.dll   # only for cu121/cu129
  LICENSE
```

## Requirements

- `cpu`: CPU with AVX2 support.

- `cu121` / `cu129`: CPU with AVX2 support, plus an NVIDIA GPU of
  [compute capability](https://developer.nvidia.com/cuda-gpus) 5.0 or higher
  (Maxwell+).

- `cu121` / `cu129`: the installed NVIDIA driver must support the selected CUDA
  runtime. Use `cu121` for machines pinned to older 12.x-capable drivers; use
  `cu129` only when the driver supports CUDA 12.9.

The minimum requirement on compute capability is 3.5, which requires manual compilation (specifying nvcc flag `-gencode arch=compute_35,code=sm_35`).

The `cpu` version does not require NVIDIA drivers or CUDA runtime libraries.

## Parameters

```python3
{bm3dcuda_rtc, bm3dcpu}.BM3D(clip clip[, clip ref=None, float[] sigma=3.0, int[] block_step=8, int[] bm_range=9, int radius=0, int[] ps_num=2, int[] ps_range=4, bint chroma=False, int device_id=0, bool fast=True, int extractor_exp=0])
```

- clip:

    The input clip. Must be of 32 bit float format. Each plane is denoised separately if `chroma` is set to `False`. Data of unprocessed planes is undefined. Frame properties of the output clip are copied from it.

- ref:

    The reference clip. Must be of the same format, width, height, number of frames as `clip`.

    Used in block-matching and as the reference in empirical Wiener filtering, i.e. `bm3d.Final` / `bm3d.VFinal`:

    ```python3
    basic = core.{bm3dcpu, bm3dcuda_rtc}.BM3D(src, radius=0)
    final = core.{bm3d...}.BM3D(src, ref=basic, radius=0)

    vbasic = core.{bm3d...}.BM3D(src, radius=radius_nonzero).bm3d.VAggregate(radius=radius_nonzero)
    vfinal = core.{bm3d...}.BM3D(src, ref=vbasic, radius=r).bm3d.VAggregate(radius=r)
    
    # alternatively, using the v2 interface
    basic_or_vbasic = core.{bm3dcpu, bm3dcuda_rtc}.BM3Dv2(src, radius=r)
    final_or_vfinal = core.{bm3d...}.BM3Dv2(src, ref=basic_or_vbasic, radius=r)
    ```

    corresponds to the followings (ignoring color space handling and other differences in implementation), respectively

    ```python3
    basic = core.bm3d.Basic(clip)
    final = core.bm3d.Final(basic, ref=basic)

    vbasic = core.bm3d.VBasic(src, radius=r).bm3d.VAggregate(radius=r, sample=1)
    vfinal = core.bm3d.VFinal(src, ref=vbasic, radius=r).bm3d.VAggregate(radius=r)
    ```

- sigma:
    The strength of denoising for each plane.

    The strength is similar (but not strictly equal) as `VapourSynth-BM3D` due to differences in implementation. (coefficient normalization is not implemented, for example)

    Default `[3,3,3]`.

- block_step, bm_range, radius, ps_num, ps_range:

    Same as those in `VapourSynth-BM3D`.

    If `chroma` is set to `True`, only the first value is in effect.

    Otherwise an array of values may be specified for each plane (except `radius`).
    
    **Note**: It is generally not recommended to take a large value of `ps_num` as current implementations do not take duplicate block-matching candidates into account during temporary searching, which may leads to regression in denoising quality. This issue is not present in `VapourSynth-BM3D`.

    **Note2**: Lowering the value of "block_step" will be useful in reducing blocking artifacts at the cost of slower processing.

- chroma:

    CBM3D algorithm. `clip` must be of `YUV444PS` format.

    Y channel is used in block-matching of chroma channels.

    Default `False`.

- device_id:

    Set GPU to be used.

    Default `0`.

- fast:

    Multi-threaded copy between CPU and GPU at the expense of 4x memory consumption.

    Default `True`.

- extractor_exp:

    Used for deterministic (bitwise) output. This parameter is not present in the `cpu` version since the implementation always produces deterministic output.

    [Pre-rounding](https://ieeexplore.ieee.org/document/6545904) is employed for associative floating-point summation.

    The value should be a positive integer not less than 3, and may need to be higher depending on the source video and filter parameters.

    Default `0`. (non-determinism)

## Notes

- `bm3d.VAggregate` should be called after temporal filtering, as in `VapourSynth-BM3D`. Alternatively, you may use the `BM3Dv2()` interface for both spatial and temporal denoising in one step.

- The `_rtc` version has three additional experimental parameters:

    - bm_error_s: (string)

        Specify cost for block similarity measurement.

        Currently implemented costs: 
        `SSD` (Sum of Squared Differences), 
        `SAD` (Sum of Absolute Differences), 
        `ZSSD` (Zero-mean SSD), 
        `ZSAD` (Zero-mean SAD), 
        `SSD/NORM`.

        Default `SSD`.

    - transform_2d_s/transform_1d_s: (string)

        Specify type of transform.

        Currently implemented transforms: 
        `DCT` (Discrete Cosine Transform), 
        `Haar` (Haar Transform), 
        `WHT` (Walsh–Hadamard Transform), 
        `Bior1.5` (transform based on a bi-orthogonal spline wavelet).

        Default `DCT`.

    These features are not implemented in the standard version due to performance and binary size concerns.

## Statistics

GPU memory consumptions:

`(ref ? 4 : 3) * (chroma ? 3 : 1) * (fast ? 4 : 1) * (2 * radius + 1) * size_of_a_single_frame`

## Compilation
- Windows release builds use MSVC for both `bm3dcpu` and `bm3dcuda_rtc`.

- The CMake configuration of `BM3DCUDA_RTC` links to NVRTC static library by default, which requires CUDA 11.5 or later.

```bash
cmake -S . -B build -G Ninja ^
  -D CMAKE_BUILD_TYPE=Release ^
  -D ENABLE_CPU=ON ^
  -D ENABLE_CUDA=OFF ^
  -D ENABLE_CUDA_RTC=ON ^
  -D ENABLE_HIP=OFF ^
  -D ENABLE_SYCL=OFF ^
  -D USE_NVRTC_STATIC=ON ^
  -D VAPOURSYNTH_INCLUDE_DIRECTORY=C:\path\to\vapoursynth\include

cmake --build build --config Release
```

For reproducible release packages, use the GitHub Actions workflow. It builds
and smoke-tests one selected variant at a time, then uploads
`bm3dcuda-cpu-win64.zip`, `bm3dcuda-cu121-win64.zip`, or
`bm3dcuda-cu129-win64.zip` to the matching release tag.
