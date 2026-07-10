from __future__ import annotations

import argparse
import os
from pathlib import Path

import vapoursynth as vs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin", type=Path)
    parser.add_argument("--dll-dir", action="append", type=Path, default=[])
    parser.add_argument("--chroma", action="store_true")
    parser.add_argument("--width", type=int, default=16)
    parser.add_argument("--height", type=int, default=16)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for dll_dir in args.dll_dir:
        os.add_dll_directory(str(dll_dir))

    core = vs.core
    if args.plugin:
        core.std.LoadPlugin(str(args.plugin))

    clip = core.std.BlankClip(
        width=args.width,
        height=args.height,
        length=1,
        format=vs.YUV444PS,
        color=[0.5, 0.5, 0.5],
    )
    out = core.bm3dcpu.BM3D(
        clip,
        sigma=[1.0, 1.0, 1.0],
        radius=0,
        chroma=args.chroma,
    )
    frame = out.get_frame(0)
    stats = core.std.PlaneStats(out).get_frame(0).props
    print(f"frame={frame.format.name} {frame.width}x{frame.height}")
    print(
        "PlaneStats "
        f"min={stats['PlaneStatsMin']} "
        f"max={stats['PlaneStatsMax']} "
        f"avg={stats['PlaneStatsAverage']}"
    )


if __name__ == "__main__":
    main()
