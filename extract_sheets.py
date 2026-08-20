#!/usr/bin/env python3
"""extract_sheets.py

Given a YouTube URL (or a local video file) of a performance where a sheet-music
score is shown on screen, detect each distinct score page, order them in
performance order, remove duplicates and blurred/transition frames, and emit a
single clean PDF.

See README.md (Japanese) for full usage / tuning documentation.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import cv2
import numpy as np

LOG = logging.getLogger("extract_sheets")

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

FEATURE_LONG_SIDE = 1000  # downscaled long side used for feature computation
POPCOUNT_TABLE = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint32)


# --------------------------------------------------------------------------
# Small utilities
# --------------------------------------------------------------------------


def find_ffmpeg() -> str:
    """Resolve an ffmpeg binary: PATH first, then imageio_ffmpeg's bundled copy."""
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "ffmpeg was not found on PATH and imageio_ffmpeg could not supply one. "
            "Install ffmpeg or `pip install imageio-ffmpeg`."
        ) from exc


def is_url(text: str) -> bool:
    try:
        parsed = urlparse(text)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def run_cmd(cmd: List[str], verbose: bool = False) -> None:
    LOG.debug("running: %s", " ".join(str(c) for c in cmd))
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE if not verbose else None,
        stderr=subprocess.PIPE if not verbose else None,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr if result.stderr is not None else "(see above)"
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(str(c) for c in cmd)}\n{stderr}"
        )


def popcount(packed: np.ndarray) -> int:
    """Count set bits in a np.packbits()-produced uint8 array."""
    return int(POPCOUNT_TABLE[packed].sum())


def pack_mask(mask: np.ndarray) -> Tuple[np.ndarray, Tuple[int, int]]:
    """Pack a boolean 2D mask into bits to keep long-run memory usage low."""
    shape = mask.shape
    return np.packbits(mask.reshape(-1)), shape


def unpack_mask(packed: np.ndarray, shape: Tuple[int, int]) -> np.ndarray:
    n = shape[0] * shape[1]
    bits = np.unpackbits(packed)[:n]
    return bits.reshape(shape).astype(bool)


def mask_diff_packed(a: np.ndarray, b: np.ndarray) -> float:
    """Normalized XOR/OR difference between two packed masks of identical shape."""
    xor = np.bitwise_xor(a, b)
    orr = np.bitwise_or(a, b)
    denom = popcount(orr)
    if denom == 0:
        return 0.0
    return popcount(xor) / denom


def mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    """IoU between two boolean masks (unpacked, possibly different-sized -> caller
    must resize first)."""
    inter = np.count_nonzero(a & b)
    union = np.count_nonzero(a | b)
    if union == 0:
        return 1.0
    return inter / union


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass
class FrameMeta:
    index: int
    path: Path
    timestamp: float
    mask_packed: Optional[np.ndarray] = None
    mask_shape: Optional[Tuple[int, int]] = None
    staff_conf: float = 0.0
    sharpness: float = 0.0

    def is_score(self, staff_threshold: float) -> bool:
        return self.staff_conf >= staff_threshold


@dataclass
class Run:
    frames: List[FrameMeta]
    kept: bool = True
    drop_reason: str = ""

    @property
    def start_ts(self) -> float:
        return self.frames[0].timestamp

    @property
    def end_ts(self) -> float:
        return self.frames[-1].timestamp

    @property
    def duration(self) -> float:
        return self.end_ts - self.start_ts

    def staff_conf_mean(self) -> float:
        return float(np.mean([f.staff_conf for f in self.frames]))

    def score_fraction(self, staff_threshold: float) -> float:
        return float(np.mean([f.is_score(staff_threshold) for f in self.frames]))


@dataclass
class Page:
    run: Run
    image: np.ndarray  # full-resolution BGR
    page_no: int = 0  # assigned after dedupe, 1-based
    kept: bool = True
    drop_reason: str = ""
    dup_of_ts: Optional[float] = None
    dhash: Optional[np.ndarray] = None
    ink_mask_small: Optional[np.ndarray] = None

    @property
    def timestamp(self) -> float:
        return self.run.start_ts


# --------------------------------------------------------------------------
# Stage 1: acquire
# --------------------------------------------------------------------------


def stage1_acquire(
    input_arg: str,
    workdir: Path,
    max_height: int,
    force: bool,
    ffmpeg_bin: str,
    verbose: bool,
    cookies: Optional[str] = None,
) -> Path:
    if not is_url(input_arg):
        local = Path(input_arg).expanduser().resolve()
        if not local.exists():
            raise FileNotFoundError(f"input path does not exist: {local}")
        LOG.info("using local video file: %s", local)
        return local

    workdir.mkdir(parents=True, exist_ok=True)
    existing = sorted(workdir.glob("source.*"))
    existing = [p for p in existing if p.suffix.lower() not in (".part", ".ytdl")]
    if existing and not force:
        LOG.info("source video already downloaded, skipping download: %s", existing[0])
        return existing[0]

    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is required to download from a URL. Install with `pip install yt-dlp`."
        ) from exc

    LOG.info("downloading with yt-dlp (max height=%s): %s", max_height, input_arg)
    # Only the picture matters, so prefer a video-only stream. That skips the
    # audio merge entirely, which both halves the download and removes any
    # dependency on yt-dlp locating a usable ffmpeg/ffprobe pair.
    fmt = (
        f"bestvideo[height<={max_height}][ext=mp4]/"
        f"bestvideo[height<={max_height}]/"
        f"best[height<={max_height}][ext=mp4]/"
        f"best[height<={max_height}]/best"
    )
    ydl_opts = {
        "format": fmt,
        "outtmpl": str(workdir / "source.%(ext)s"),
        "quiet": not verbose,
        "noprogress": not verbose,
        # Pass the binary itself, not its directory: yt-dlp only probes a
        # directory for files literally named ffmpeg/ffprobe, which misses
        # imageio-ffmpeg's versioned filename.
        "ffmpeg_location": ffmpeg_bin,
        "retries": 3,
        "noplaylist": True,
    }
    if cookies:
        ydl_opts["cookiefile"] = str(Path(cookies).expanduser())
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([input_arg])

    downloaded = sorted(workdir.glob("source.*"))
    downloaded = [p for p in downloaded if p.suffix.lower() not in (".part", ".ytdl")]
    if not downloaded:
        raise RuntimeError("yt-dlp reported success but no source.* file was found")
    LOG.info("downloaded: %s", downloaded[0])
    return downloaded[0]


# --------------------------------------------------------------------------
# Stage 2: sample frames
# --------------------------------------------------------------------------


def stage2_sample_frames(
    video_path: Path,
    frames_dir: Path,
    fps: float,
    start: Optional[float],
    end: Optional[float],
    force: bool,
    ffmpeg_bin: str,
    verbose: bool,
) -> List[FrameMeta]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(frames_dir.glob("frame_*.jpg"))
    if existing and not force:
        LOG.info("reusing %d already-extracted frames in %s", len(existing), frames_dir)
    else:
        for f in existing:
            f.unlink()
        cmd = [ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "warning" if not verbose else "info"]
        if start is not None:
            cmd += ["-ss", str(start)]
        cmd += ["-i", str(video_path)]
        if end is not None:
            duration = max(0.0, end - (start or 0.0))
            cmd += ["-t", str(duration)]
        cmd += ["-vf", f"fps={fps}", "-qscale:v", "2", str(frames_dir / "frame_%06d.jpg")]
        LOG.info("extracting frames at %s fps", fps)
        run_cmd(cmd, verbose=verbose)
        existing = sorted(frames_dir.glob("frame_*.jpg"))

    if not existing:
        raise RuntimeError("no frames were extracted; check --start/--end and the video file")

    base = start or 0.0
    frames = [
        FrameMeta(index=i, path=p, timestamp=base + i / fps) for i, p in enumerate(existing)
    ]
    LOG.info("sampled %d frames (%.2fs .. %.2fs)", len(frames), frames[0].timestamp, frames[-1].timestamp)
    return frames


# --------------------------------------------------------------------------
# Stage 3: score-region detection & per-frame features
# --------------------------------------------------------------------------


def downscale_gray(img_bgr: np.ndarray, target_size: Optional[Tuple[int, int]]) -> Tuple[np.ndarray, Tuple[int, int]]:
    """Return (gray, (w,h)) downscaled so the long side is FEATURE_LONG_SIDE.
    If target_size is given, resize to that exact (w,h) instead (keeps all frames
    of a run directly comparable pixel-for-pixel)."""
    h, w = img_bgr.shape[:2]
    if target_size is None:
        scale = FEATURE_LONG_SIDE / max(h, w)
        target_w, target_h = max(1, round(w * scale)), max(1, round(h * scale))
    else:
        target_w, target_h = target_size
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (target_w, target_h), interpolation=cv2.INTER_AREA)
    return gray, (target_w, target_h)


def ink_mask_from_gray(gray: np.ndarray, invert: bool) -> np.ndarray:
    """Otsu-threshold to a boolean mask of 'ink' (the notation).
    Score assumed dark-on-light by default; --invert flips this for dark-mode
    scores (light notation on a dark background)."""
    flag = cv2.THRESH_BINARY + cv2.THRESH_OTSU if invert else cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    _, mask = cv2.threshold(gray, 0, 255, flag)
    return mask > 0


def rolling_median_1d(x: np.ndarray, window: int) -> np.ndarray:
    """Simple O(n*window) rolling median with edge padding - used to estimate a
    local baseline for the row-ink-density profile (robust to letterboxing bars
    and note-blob density, which vary slowly compared to staff-line spikes)."""
    if window < 3:
        return x.copy()
    half = window // 2
    padded = np.pad(x, (half, half), mode="edge")
    out = np.empty_like(x)
    for i in range(len(x)):
        out[i] = np.median(padded[i : i + window])
    return out


def staff_confidence(mask: np.ndarray) -> float:
    """Heuristic confidence in [0,1] that `mask` contains at least one group of
    5 regularly-spaced horizontal staff lines.

    Uses a local (rolling-median) baseline subtraction on the row-ink-density
    profile rather than an absolute threshold, so that slowly-varying content
    (black letterbox bars, note-blob density) does not swamp the sharp, narrow
    spikes that real staff lines produce."""
    h, w = mask.shape
    if h < 10 or w < 10:
        return 0.0
    row_frac = mask.sum(axis=1) / float(w)
    baseline = rolling_median_1d(row_frac, window=max(15, (h // 25) | 1))
    highpass = row_frac - baseline
    peak_thresh = 0.15
    rows = np.where(highpass > peak_thresh)[0]
    if len(rows) < 5:
        return 0.0

    # cluster adjacent candidate rows into line centers
    clusters: List[int] = []
    current = [int(rows[0])]
    for r in rows[1:]:
        if r - current[-1] <= 2:
            current.append(int(r))
        else:
            clusters.append(int(round(np.mean(current))))
            current = [int(r)]
    clusters.append(int(round(np.mean(current))))

    if len(clusters) < 5:
        return 0.0

    min_span, max_span = 8, int(0.35 * h)
    best = 0.0
    for i in range(len(clusters) - 4):
        window = clusters[i : i + 5]
        gaps = np.diff(window)
        mean_gap = float(gaps.mean())
        if mean_gap <= 1.0:
            continue
        span = window[-1] - window[0]
        if span < min_span or span > max_span:
            continue
        cv_gap = float(gaps.std()) / mean_gap
        regularity = max(0.0, 1.0 - cv_gap * 4.0)
        best = max(best, regularity)
    return best


def sharpness_score(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def stage3_compute_features(frames: List[FrameMeta], invert: bool) -> None:
    LOG.info("computing per-frame features for %d frames", len(frames))
    target_size: Optional[Tuple[int, int]] = None
    for i, fm in enumerate(frames):
        img = cv2.imread(str(fm.path))
        if img is None:
            LOG.warning("could not read frame %s, skipping features (treated as blank)", fm.path)
            continue
        gray, target_size = downscale_gray(img, target_size)
        mask = ink_mask_from_gray(gray, invert)
        fm.mask_packed, fm.mask_shape = pack_mask(mask)
        fm.staff_conf = staff_confidence(mask)
        fm.sharpness = sharpness_score(gray)
        if i % 200 == 0:
            LOG.debug("features: %d/%d", i, len(frames))


# --------------------------------------------------------------------------
# Stage 4: segment into stable runs
# --------------------------------------------------------------------------


def stage4_segment(
    frames: List[FrameMeta],
    change_threshold: float,
    min_page_seconds: float,
    staff_threshold: float,
) -> List[Run]:
    if not frames:
        return []

    boundaries = [0]
    for i in range(1, len(frames)):
        prev, cur = frames[i - 1], frames[i]
        if prev.mask_packed is None or cur.mask_packed is None:
            continue
        diff = mask_diff_packed(prev.mask_packed, cur.mask_packed)
        if diff > change_threshold:
            boundaries.append(i)
    boundaries.append(len(frames))
    boundaries = sorted(set(boundaries))

    runs: List[Run] = []
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        run_frames = frames[start:end]
        if not run_frames:
            continue
        run = Run(frames=run_frames)
        if run.duration < min_page_seconds:
            run.kept = False
            run.drop_reason = f"too short ({run.duration:.2f}s < {min_page_seconds}s) - likely a transition"
        elif run.score_fraction(staff_threshold) < 0.5:
            run.kept = False
            run.drop_reason = (
                f"mostly not sheet music (staff conf mean={run.staff_conf_mean():.2f} < "
                f"threshold={staff_threshold})"
            )
        runs.append(run)

    LOG.info(
        "segmented into %d runs (%d kept, %d dropped)",
        len(runs),
        sum(r.kept for r in runs),
        sum(not r.kept for r in runs),
    )
    return runs


# --------------------------------------------------------------------------
# Stage 5: build one clean image per run (median compositing)
# --------------------------------------------------------------------------


def stage5_build_pages(runs: List[Run], median_frames: int, debug_dir: Optional[Path]) -> List[Page]:
    pages: List[Page] = []
    kept_runs = [r for r in runs if r.kept]
    LOG.info("building composite images for %d pages", len(kept_runs))

    for run_idx, run in enumerate(kept_runs):
        frames = run.frames
        sharpness_values = np.array([f.sharpness for f in frames])
        median_sharp = float(np.median(sharpness_values))

        if len(frames) <= median_frames:
            candidate_idxs = list(range(len(frames)))
        else:
            candidate_idxs = sorted(set(np.linspace(0, len(frames) - 1, median_frames).round().astype(int).tolist()))

        usable_idxs = [i for i in candidate_idxs if frames[i].sharpness >= median_sharp]

        image: Optional[np.ndarray] = None
        if len(usable_idxs) >= 2:
            imgs = []
            for i in usable_idxs:
                img = cv2.imread(str(frames[i].path))
                if img is not None:
                    imgs.append(img.astype(np.float32))
            if len(imgs) >= 2:
                stack = np.stack(imgs, axis=0)
                image = np.median(stack, axis=0).astype(np.uint8)

        if image is None:
            # fallback: single sharpest frame in the run
            best_i = int(np.argmax(sharpness_values))
            img = cv2.imread(str(frames[best_i].path))
            if img is None:
                LOG.warning("run at %.2fs produced no readable frames, skipping", run.start_ts)
                continue
            image = img
            LOG.debug("run at %.2fs: falling back to single sharpest frame", run.start_ts)

        page = Page(run=run, image=image)
        pages.append(page)

        if debug_dir is not None:
            debug_dir.mkdir(parents=True, exist_ok=True)
            out = debug_dir / f"run_{run_idx:03d}_t{run.start_ts:.1f}s.png"
            cv2.imwrite(str(out), image)

    return pages


# --------------------------------------------------------------------------
# Stage 6: dedupe
# --------------------------------------------------------------------------


def dhash(gray: np.ndarray, hash_size: int = 8) -> np.ndarray:
    """Difference hash implemented with numpy: resize to (hash_size+1, hash_size)
    and compare each pixel to its right neighbour. Returns a boolean vector of
    length hash_size*hash_size."""
    resized = cv2.resize(gray, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)
    diff = resized[:, 1:] > resized[:, :-1]
    return diff.flatten()


def hamming(a: np.ndarray, b: np.ndarray) -> int:
    return int(np.count_nonzero(a != b))


def stage6_dedupe(pages: List[Page], hash_threshold: int, iou_threshold: float, invert: bool) -> List[Page]:
    # pages are already in temporal (first-appearance) order
    small_size = (256, 256)
    for p in pages:
        gray = cv2.cvtColor(p.image, cv2.COLOR_BGR2GRAY)
        gray_small = cv2.resize(gray, small_size, interpolation=cv2.INTER_AREA)
        p.dhash = dhash(gray_small)
        p.ink_mask_small = ink_mask_from_gray(gray_small, invert)

    kept: List[Page] = []
    for p in pages:
        dup_target: Optional[Page] = None
        for k in kept:
            hd = hamming(p.dhash, k.dhash)
            if hd > hash_threshold:
                continue
            iou = mask_iou(p.ink_mask_small, k.ink_mask_small)
            if iou >= iou_threshold:
                dup_target = k
                break
        if dup_target is not None:
            p.kept = False
            p.dup_of_ts = dup_target.timestamp
            p.drop_reason = f"duplicate of page at {dup_target.timestamp:.2f}s (hamming<= {hash_threshold}, iou>={iou_threshold})"
            LOG.info(
                "dropping duplicate page at %.2fs (matches page at %.2fs)",
                p.timestamp,
                dup_target.timestamp,
            )
        else:
            kept.append(p)

    for i, p in enumerate(kept, start=1):
        p.page_no = i

    LOG.info("dedupe: %d unique pages kept out of %d candidates", len(kept), len(pages))
    return kept


# --------------------------------------------------------------------------
# Stage 7: crop & export
# --------------------------------------------------------------------------


def parse_crop(spec: str) -> Tuple[float, float, float, float]:
    parts = spec.split(",")
    if len(parts) != 4:
        raise ValueError("--crop must be 'x,y,w,h' as fractions of the frame (0-1)")
    x, y, w, h = (float(p) for p in parts)
    for v, name in ((x, "x"), (y, "y"), (w, "w"), (h, "h")):
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"--crop value {name}={v} out of range [0,1]")
    return x, y, w, h


def apply_manual_crop(image: np.ndarray, crop: Tuple[float, float, float, float]) -> np.ndarray:
    h, w = image.shape[:2]
    x, y, cw, ch = crop
    x0, y0 = int(x * w), int(y * h)
    x1, y1 = int((x + cw) * w), int((y + ch) * h)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("manual --crop produced an empty region")
    return image[y0:y1, x0:x1]


def compute_autocrop_box(pages: List[Page], invert: bool, margin: int) -> Tuple[int, int, int, int]:
    """Union bounding box of ink across all kept pages, in the (shared) pixel
    coordinate space of the (already manually-cropped) page images."""
    min_x0, min_y0 = None, None
    max_x1, max_y1 = None, None
    for p in pages:
        gray = cv2.cvtColor(p.image, cv2.COLOR_BGR2GRAY)
        mask = ink_mask_from_gray(gray, invert)
        ys, xs = np.where(mask)
        if len(xs) == 0:
            continue
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        min_x0 = x0 if min_x0 is None else min(min_x0, x0)
        min_y0 = y0 if min_y0 is None else min(min_y0, y0)
        max_x1 = x1 if max_x1 is None else max(max_x1, x1)
        max_y1 = y1 if max_y1 is None else max(max_y1, y1)

    if min_x0 is None:
        h, w = pages[0].image.shape[:2]
        return 0, 0, w, h

    h, w = pages[0].image.shape[:2]
    x0 = max(0, min_x0 - margin)
    y0 = max(0, min_y0 - margin)
    x1 = min(w, max_x1 + margin)
    y1 = min(h, max_y1 + margin)
    return x0, y0, x1 - x0, y1 - y0


def stage7_crop_and_export(
    pages: List[Page],
    manual_crop: Optional[Tuple[float, float, float, float]],
    autocrop: bool,
    margin: int,
    invert: bool,
    pages_dir: Path,
    output_path: Path,
) -> List[Path]:
    if not pages:
        raise RuntimeError("no pages survived the pipeline; nothing to export")

    if manual_crop is not None:
        for p in pages:
            p.image = apply_manual_crop(p.image, manual_crop)

    # All page images must share dimensions for a uniform crop box / clean PDF.
    shapes = {p.image.shape[:2] for p in pages}
    if len(shapes) > 1:
        target_h = min(s[0] for s in shapes)
        target_w = min(s[1] for s in shapes)
        for p in pages:
            if p.image.shape[:2] != (target_h, target_w):
                p.image = cv2.resize(p.image, (target_w, target_h), interpolation=cv2.INTER_AREA)

    if autocrop:
        box = compute_autocrop_box(pages, invert, margin)
        x0, y0, w, h = box
        LOG.info("auto-crop box: x=%d y=%d w=%d h=%d (margin=%d)", x0, y0, w, h, margin)
        for p in pages:
            p.image = p.image[y0 : y0 + h, x0 : x0 + w]

    pages_dir.mkdir(parents=True, exist_ok=True)
    out_paths: List[Path] = []
    for p in pages:
        out_path = pages_dir / f"page_{p.page_no:02d}.png"
        cv2.imwrite(str(out_path), p.image)
        out_paths.append(out_path)

    import img2pdf

    with open(output_path, "wb") as f:
        f.write(img2pdf.convert([str(pp) for pp in out_paths]))
    LOG.info("wrote %d pages to %s", len(out_paths), output_path)
    return out_paths


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def build_and_print_report(all_runs: List[Run], all_pages: List[Page], report_path: Optional[Path]) -> None:
    rows = []
    dedupe_by_run_start = {p.run.start_ts: p for p in all_pages}

    header = f"{'idx':>3} {'start':>8} {'end':>8} {'dur':>6} {'frames':>6} {'staff':>6} {'status':<50}"
    print(header)
    print("-" * len(header))

    idx = 0
    for run in all_runs:
        idx += 1
        status: str
        dup_ts = None
        if not run.kept:
            status = f"DROPPED - {run.drop_reason}"
        else:
            page = dedupe_by_run_start.get(run.start_ts)
            if page is None:
                status = "DROPPED - no readable frames"
            elif page.kept:
                status = f"KEPT as page_{page.page_no:02d}.png"
            else:
                status = f"DEDUPED - {page.drop_reason}"
                dup_ts = page.dup_of_ts

        print(
            f"{idx:>3} {run.start_ts:>8.2f} {run.end_ts:>8.2f} {run.duration:>6.2f} "
            f"{len(run.frames):>6} {run.staff_conf_mean():>6.2f} {status:<50}"
        )
        rows.append(
            {
                "index": idx,
                "start_ts": run.start_ts,
                "end_ts": run.end_ts,
                "duration": run.duration,
                "frame_count": len(run.frames),
                "staff_confidence_mean": run.staff_conf_mean(),
                "status": status,
                "duplicate_of_ts": dup_ts,
            }
        )

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump({"runs": rows}, f, indent=2, ensure_ascii=False)
        LOG.info("wrote report to %s", report_path)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Detect sheet-music pages shown in a performance video and export a clean PDF.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("input", help="YouTube URL or path to a local video file")
    p.add_argument("--workdir", type=Path, default=Path("./work"), help="working directory for intermediates")
    p.add_argument("--output", type=Path, default=Path("sheets.pdf"), help="output PDF path")
    p.add_argument("--max-height", type=int, default=1080, help="cap download resolution height")
    p.add_argument(
        "--cookies",
        default=None,
        help="Netscape-format cookie file passed to yt-dlp; needed when YouTube "
             "demands sign-in or a bot check for the video",
    )
    p.add_argument("--force", action="store_true", help="ignore cached intermediates and redo everything")

    p.add_argument("--fps", type=float, default=2.0, help="frame sampling rate")
    p.add_argument("--start", type=float, default=None, help="start time in seconds (analysis range)")
    p.add_argument("--end", type=float, default=None, help="end time in seconds (analysis range)")

    p.add_argument("--invert", action="store_true", help="score is light-on-dark (dark-mode) instead of dark-on-light")
    p.add_argument("--staff-threshold", type=float, default=0.35, help="min staff-line confidence [0,1] to classify a frame as sheet music")

    p.add_argument("--change-threshold", type=float, default=0.05, help="normalized ink-mask diff that marks a page boundary")
    p.add_argument("--min-page-seconds", type=float, default=1.0, help="minimum run duration to be considered a real page (else transition)")

    p.add_argument("--median-frames", type=int, default=15, help="max frames per run used for the median composite")

    p.add_argument("--hash-threshold", type=int, default=6, help="max dHash hamming distance to consider pages duplicates")
    p.add_argument("--iou-threshold", type=float, default=0.85, help="min ink-mask IoU to consider pages duplicates")

    p.add_argument("--margin", type=int, default=12, help="padding in px added around the auto-crop bounding box")
    p.add_argument("--no-autocrop", dest="autocrop", action="store_false", help="disable automatic crop to the union of ink across pages")
    p.add_argument("--crop", type=str, default=None, help="manual crop 'x,y,w,h' as fractions of the frame (0-1), applied before auto-crop")

    p.add_argument("--dump-report", action="store_true", help="write workdir/report.json in addition to the printed table")
    p.add_argument("--debug-frames", action="store_true", help="save each run's pre-dedupe composite image to workdir/debug/")
    p.add_argument("--verbose", action="store_true", help="verbose logging to stderr")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    try:
        ffmpeg_bin = find_ffmpeg()
    except RuntimeError as exc:
        LOG.error(str(exc))
        return 1

    workdir: Path = args.workdir
    workdir.mkdir(parents=True, exist_ok=True)

    manual_crop = None
    if args.crop:
        try:
            manual_crop = parse_crop(args.crop)
        except ValueError as exc:
            LOG.error("invalid --crop: %s", exc)
            return 1

    try:
        video_path = stage1_acquire(
            args.input,
            workdir,
            args.max_height,
            args.force,
            ffmpeg_bin,
            args.verbose,
            cookies=args.cookies,
        )
        frames_dir = workdir / "frames"
        frames = stage2_sample_frames(
            video_path, frames_dir, args.fps, args.start, args.end, args.force, ffmpeg_bin, args.verbose
        )
        stage3_compute_features(frames, args.invert)
        runs = stage4_segment(frames, args.change_threshold, args.min_page_seconds, args.staff_threshold)

        debug_dir = (workdir / "debug") if args.debug_frames else None
        pages = stage5_build_pages(runs, args.median_frames, debug_dir)
        if not pages:
            LOG.error("no candidate pages were produced; try lowering --staff-threshold or --min-page-seconds")
            return 1

        kept_pages = stage6_dedupe(pages, args.hash_threshold, args.iou_threshold, args.invert)
        if not kept_pages:
            LOG.error("all candidate pages were dropped by dedupe; check --hash-threshold/--iou-threshold")
            return 1

        pages_dir = workdir / "pages"
        stage7_crop_and_export(kept_pages, manual_crop, args.autocrop, args.margin, args.invert, pages_dir, args.output)

        report_path = (workdir / "report.json") if args.dump_report else None
        build_and_print_report(runs, pages, report_path)

        print(f"\nDone: {len(kept_pages)} pages written to {args.output}", file=sys.stderr)
        return 0
    except Exception as exc:  # top-level safety net -> non-zero exit + message
        LOG.error("failed: %s", exc, exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    sys.exit(main())
