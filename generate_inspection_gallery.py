#!/usr/bin/env python3
"""
generate_inspection_gallery.py

Generates high-resolution diagnostic plots for every .fit file in the PushUp dataset,
showing:
  1. Raw Acceleration Magnitude & Floor Impact Rejection
  2. Causal Forearm Tilt Wave (Green = Y Tilt Peak on Descent, Blue = X Plank Support)
  3. Raw 3-Axis Acceleration Components (Orientation & Gravity)

Saves sorted visual cards into inspection_gallery/ for easy visual auditing.
"""

import os
import sys
import glob
from typing import List, Dict, Any, Tuple, Optional
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from detect_pushups import (
    DETECTOR_CONFIG,
    extract_high_freq_accel,
    extract_true_reps,
    simulate_pushup_detector,
    plot_pushup_inspection,
)


def load_dataset(data_dir: str) -> List[Dict[str, Any]]:
    """
    Discovers and extracts raw accelerometer signals and true reps
    for all .fit workout sets in data_dir.
    """
    fit_paths = sorted(glob.glob(os.path.join(data_dir, "*.fit")))
    dataset = []

    for path in fit_paths:
        fname = os.path.basename(path)
        df = extract_high_freq_accel(path)
        if df is None or len(df) == 0:
            continue

        true_reps = extract_true_reps(path)
        dataset.append({
            "path": path,
            "filename": fname,
            "df": df,
            "true_reps": true_reps,
            "duration_s": len(df) / 100.0,
            "n_samples": len(df),
        })

    return dataset


def generate_gallery(data_dir: str = "data", output_dir: str = "inspection_gallery"):
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(workspace_dir, data_dir)
    gallery_path = os.path.join(workspace_dir, output_dir)
    os.makedirs(gallery_path, exist_ok=True)

    print(f"Loading PushUp dataset from: {data_path}")
    dataset = load_dataset(data_path)
    print(f"Loaded {len(dataset)} valid sets. Generating inspection gallery in '{output_dir}/'...\n")

    exact_matches = []
    suspect_matches = []
    mismatches = []

    # Sort dataset chronologically / by filename
    dataset.sort(key=lambda d: d["filename"])

    fs = 100.0  # 100 Hz hardware sensor sample rate

    for idx, item in enumerate(dataset, 1):
        fname = item["filename"]
        df = item["df"]
        true_reps = item["true_reps"]
        n_samples = item["n_samples"]
        duration_s = item["duration_s"]

        (
            confirmed,
            rep_peaks,
            cancelled,
            narrow,
            mount_idx,
            dismount_idx,
            settle_idx,
            rep_th_hist,
            reset_th_hist,
            x_smooth,
            y_smooth,
        ) = simulate_pushup_detector(df)

        det_reps = len(confirmed)
        error = det_reps - true_reps if true_reps is not None else 0

        # Categorize
        if true_reps is not None:
            if error == 0:
                status = "MATCH"
                near_end = any((n_samples - r) < 150 for r in confirmed)
                if cancelled or near_end:
                    suspect_matches.append((fname, true_reps, det_reps, error, duration_s, len(cancelled)))
                else:
                    exact_matches.append((fname, true_reps, det_reps, error, duration_s))
            elif error > 0:
                status = "OVER"
                mismatches.append((fname, true_reps, det_reps, error, duration_s))
            else:
                status = "UNDER"
                mismatches.append((fname, true_reps, det_reps, error, duration_s))
        else:
            status = "UNLABELED"

        # Save individual diagnostic plot
        base_name = os.path.splitext(fname)[0]
        out_fname = f"{idx:02d}_{status}_{base_name}_T{true_reps}_D{det_reps}.png"
        out_path = os.path.join(gallery_path, out_fname)

        # Hijack plt.show to save the file
        def _save_show(save_target=out_path):
            plt.savefig(save_target, dpi=120, bbox_inches="tight")
            plt.close()

        orig_show = plt.show
        plt.show = _save_show
        try:
            plot_pushup_inspection(
                df=df,
                fname=fname,
                confirmed=confirmed,
                rep_peaks=rep_peaks,
                cancelled=cancelled,
                narrow=narrow,
                mount_idx=mount_idx,
                dismount_idx=dismount_idx,
                settle_idx=settle_idx,
                rep_th_hist=rep_th_hist,
                reset_th_hist=reset_th_hist,
                x_smooth=x_smooth,
                y_smooth=y_smooth,
                true_reps=true_reps,
                fs=fs,
            )
        finally:
            plt.show = orig_show

        print(f"  [{idx}/{len(dataset)}] {out_fname}")

    print(f"\nSuccessfully generated all {len(dataset)} diagnostic cards in: {gallery_path}\n")

    # ========================================================================
    # Summary Classification Report
    # ========================================================================
    print("=" * 80)
    print(" PUSHUP INSPECTION GALLERY AUDIT SUMMARY")
    print("=" * 80)
    print(f" Total Workout Sets Audited : {len(dataset)}")
    print(f" - Definite Exact Matches   : {len(exact_matches)}")
    print(f" - Suspect Matches          : {len(suspect_matches)} (count matches, but dismount/borderline trigger)")
    print(f" - Clear Mismatches         : {len(mismatches)} (undercounts / overcounts)")
    print("-" * 80)

    print("\n[1] DEFINITE EXACT MATCHES (Clean Rep Transitions):")
    print(f" {'Filename':<48} | {'True':>4} | {'Det':>4} | {'Dur':>6}")
    print("-" * 70)
    for m in exact_matches:
        print(f" {m[0]:<48} | {m[1]:>4} | {m[2]:>4} | {m[4]:>5.1f}s")

    if suspect_matches:
        print("\n[2] SUSPECT MATCHES (Verify trigger location / dismount proximity):")
        print(f" {'Filename':<48} | {'True':>4} | {'Det':>4} | {'Dur':>6} | Notes")
        print("-" * 85)
        for m in suspect_matches:
            notes = []
            if m[5] > 0:
                notes.append(f"{m[5]} rep(s) cancelled")
            notes.append("Rep trigger near end of set")
            print(f" {m[0]:<48} | {m[1]:>4} | {m[2]:>4} | {m[4]:>5.1f}s | {', '.join(notes)}")

    if mismatches:
        print("\n[3] CLEAR MISMATCHES (Requires algorithm adjustment):")
        print(f" {'Filename':<48} | {'True':>4} | {'Det':>4} | {'Error':>6} | {'Dur':>6} | Type")
        print("-" * 85)
        for m in mismatches:
            t = "Overcount" if m[3] > 0 else "Undercount"
            sign = "+" if m[3] > 0 else ""
            print(f" {m[0]:<48} | {m[1]:>4} | {m[2]:>4} | {sign}{m[3]:>5d} | {m[4]:>5.1f}s | {t}")
    print("=" * 80)


if __name__ == "__main__":
    generate_gallery()
