#!/usr/bin/env python3
"""
plot_dataset_errors.py

Generates a comprehensive 4-quadrant diagnostic dashboard for the PushUp dataset:
1. Subplot 1: Distribution of True Reps (Histogram / Bar chart)
2. Subplot 2: True Reps vs. Detected Reps (Scatter plot with y = x parity reference line)
3. Subplot 3: Residual / Error Plot (True - Detected vs. Duration and Rep Count)
4. Subplot 4: Summary table of dataset performance and any residual outliers
Saves high-resolution figure to dataset_analysis.png.
"""

import os
import sys
import glob
from typing import List, Dict, Any
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from detect_pushups import (
    extract_high_freq_accel,
    extract_true_reps,
    simulate_pushup_detector,
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
        if true_reps is None:
            continue

        dataset.append({
            "path": path,
            "filename": fname,
            "df": df,
            "true_reps": true_reps,
            "duration_s": len(df) / 100.0,
            "n_samples": len(df),
        })

    return dataset


def evaluate_dataset(dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Runs the PushUp detector across all dataset files and aggregates accuracy metrics.
    """
    results = []
    exact_matches = 0
    overcount_sets = 0
    undercount_sets = 0
    abs_errors = []

    for item in dataset:
        trace = simulate_pushup_detector(item["df"])
        confirmed = trace[0]
        det_reps = len(confirmed)
        true_reps = item["true_reps"]
        error = det_reps - true_reps

        if error == 0:
            exact_matches += 1
        elif error > 0:
            overcount_sets += 1
        else:
            undercount_sets += 1

        abs_errors.append(abs(error))
        results.append({
            "filename": item["filename"],
            "true_reps": true_reps,
            "detected_reps": det_reps,
            "error": error,
            "duration_s": item["duration_s"],
        })

    return {
        "file_results": results,
        "exact_matches": exact_matches,
        "overcount_sets": overcount_sets,
        "undercount_sets": undercount_sets,
        "mae": float(np.mean(abs_errors)) if abs_errors else 0.0,
        "total_sets": len(dataset),
    }


def generate_dashboard(output_path: str = "dataset_analysis.png"):
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(workspace_dir, "data")

    print(f"Loading PushUp dataset from: {data_dir}")
    dataset = load_dataset(data_dir)
    print(f"Loaded {len(dataset)} valid workout sets.")

    # Evaluate using default detector parameters
    metrics = evaluate_dataset(dataset)

    results = metrics["file_results"]
    filenames = [r["filename"] for r in results]
    true_reps = np.array([r["true_reps"] for r in results])
    det_reps = np.array([r["detected_reps"] for r in results])
    errors = det_reps - true_reps  # Positive: overcount, Negative: undercount
    residuals = true_reps - det_reps  # Positive: undercounted reps
    durations = np.array([r["duration_s"] for r in results])

    fig = plt.figure(figsize=(16, 12), dpi=150)
    plt.suptitle("Garmin Push-Up Dataset Analysis & Repetition Detector Diagnostics", fontsize=16, fontweight="bold", y=0.98)

    # ------------------------------------------------------------------------
    # Subplot 1: Distribution of True Reps
    # ------------------------------------------------------------------------
    ax1 = fig.add_subplot(2, 2, 1)
    unique_reps, counts = np.unique(true_reps, return_counts=True)
    bars = ax1.bar(unique_reps, counts, width=0.8, color="#5b2c8f", edgecolor="black", alpha=0.85)
    ax1.set_title(f"1. Distribution of True Reps ({len(results)} Push-Up Sets)", fontsize=12, fontweight="bold")
    ax1.set_xlabel("True Rep Count", fontsize=10)
    ax1.set_ylabel("Number of Workout Sets", fontsize=10)
    ax1.grid(True, linestyle=":", alpha=0.6, axis="y")
    ax1.set_xticks(np.arange(0, max(unique_reps) + 2, 2 if max(unique_reps) > 10 else 1))
    for b in bars:
        h = b.get_height()
        ax1.text(b.get_x() + b.get_width() / 2.0, h + 0.08, str(int(h)), ha="center", va="bottom", fontsize=9, fontweight="bold")

    # ------------------------------------------------------------------------
    # Subplot 2: True Reps vs. Detected Reps (Parity Plot)
    # ------------------------------------------------------------------------
    ax2 = fig.add_subplot(2, 2, 2)
    max_val = max(np.max(true_reps), np.max(det_reps)) + 2
    ax2.plot([0, max_val], [0, max_val], "k--", lw=1.5, label="Ideal Parity (y = x)")

    # Color code points: green = exact match, red = undercount, blue = overcount
    colors = []
    for e in errors:
        if e == 0:
            colors.append("#28a745")  # Green
        elif e < 0:
            colors.append("#dc3545")  # Red (undercount)
        else:
            colors.append("#007bff")  # Blue (overcount)

    ax2.scatter(true_reps, det_reps, c=colors, s=80, edgecolors="black", linewidth=0.8, zorder=5)
    ax2.set_title(f"2. True Reps vs. Detected Reps (MAE = {metrics['mae']:.2f})", fontsize=12, fontweight="bold")
    ax2.set_xlabel("True Reps (Recorded in FIT Session)", fontsize=10)
    ax2.set_ylabel("Detected Reps (PushUpDetector Engine)", fontsize=10)
    ax2.set_xlim(0, max_val)
    ax2.set_ylim(0, max_val)
    ax2.grid(True, linestyle=":", alpha=0.6)

    # Custom legend
    legend_elements = [
        Line2D([0], [0], color="k", linestyle="--", label="Ideal Parity (y = x)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#28a745", markersize=8, markeredgecolor="k", label=f"Exact Match ({metrics['exact_matches']})"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#dc3545", markersize=8, markeredgecolor="k", label=f"Undercount ({metrics['undercount_sets']})"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#007bff", markersize=8, markeredgecolor="k", label=f"Overcount ({metrics['overcount_sets']})"),
    ]
    ax2.legend(handles=legend_elements, loc="upper left", fontsize=9)

    # ------------------------------------------------------------------------
    # Subplot 3: Residual / Error Plot (True - Detected vs Duration)
    # ------------------------------------------------------------------------
    ax3 = fig.add_subplot(2, 2, 3)
    ax3.axhline(0, color="black", linestyle="-", lw=1.2)
    ax3.axhspan(-1, 1, color="green", alpha=0.12, label="Acceptable Band (±1 Rep)")

    sc = ax3.scatter(durations, residuals, c=true_reps, cmap="viridis", s=80, edgecolors="black", linewidth=0.8, zorder=5)
    cbar = plt.colorbar(sc, ax=ax3)
    cbar.set_label("True Rep Count", fontsize=9)

    ax3.set_title("3. Detection Residuals (True - Detected) vs. Workout Duration", fontsize=12, fontweight="bold")
    ax3.set_xlabel("Workout Duration (seconds)", fontsize=10)
    ax3.set_ylabel("Residual: True - Detected Reps", fontsize=10)
    ax3.set_ylim(-3, 3)
    ax3.grid(True, linestyle=":", alpha=0.6)
    ax3.legend(loc="upper left", fontsize=9)

    # Annotate points with filenames/reps
    for i, r in enumerate(results):
        label_text = f"{r['true_reps']}r"
        if residuals[i] != 0:
            label_text += f" ({residuals[i]:+d})"
        ax3.annotate(
            label_text,
            (durations[i], residuals[i]),
            xytext=(0, 9 if residuals[i] >= 0 else -14),
            textcoords="offset points",
            fontsize=8,
            ha="center",
            fontweight="bold",
            color="#155724" if residuals[i] == 0 else ("#b30000" if residuals[i] > 0 else "#004085")
        )

    # ------------------------------------------------------------------------
    # Subplot 4: Summary Table
    # ------------------------------------------------------------------------
    ax4 = fig.add_subplot(2, 2, 4)
    ax4.axis("off")
    ax4.set_title("4. Dataset Summary & Performance Breakdown", fontsize=12, fontweight="bold")

    table_data = []
    for r in results:
        sign = "+" if r["error"] > 0 else ""
        short_name = r["filename"]
        if len(short_name) > 38:
            short_name = short_name[:16] + "..." + short_name[-18:]
        table_data.append([
            short_name,
            str(r["true_reps"]),
            str(r["detected_reps"]),
            f"{sign}{r['error']}" if r["error"] != 0 else "0",
            f"{r['duration_s']:.1f}s"
        ])

    table = ax4.table(
        cellText=table_data,
        colLabels=["Filename", "True", "Det", "Error", "Duration"],
        colWidths=[0.46, 0.12, 0.12, 0.14, 0.16],
        loc="center",
        cellLoc="center"
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    table.scale(1.0, 1.4)

    # Style header row
    for col_idx in range(5):
        cell = table[(0, col_idx)]
        cell.set_facecolor("#5b2c8f")
        cell.set_text_props(color="white", weight="bold")

    # Style data rows based on exact match vs mismatch
    for row_idx, r in enumerate(results, 1):
        color = "#e8f5e9" if r["error"] == 0 else ("#ffebee" if r["error"] < 0 else "#e3f2fd")
        for col_idx in range(5):
            table[(row_idx, col_idx)].set_facecolor(color)

    plt.tight_layout(rect=[0, 0.02, 1, 0.96])
    fig_path = os.path.join(workspace_dir, output_path)
    plt.savefig(fig_path, dpi=150)
    plt.close()
    print(f"Diagnostic dashboard saved successfully to: {fig_path}\n")

    # Print summary metrics to console
    print("=" * 60)
    print(" PUSHUP DATASET EVALUATION SUMMARY")
    print("=" * 60)
    print(f" Total Workout Sets   : {metrics['total_sets']}")
    print(f" Exact Matches (100%) : {metrics['exact_matches']} ({metrics['exact_matches']/metrics['total_sets']*100:.1f}%)")
    print(f" Undercount Sets      : {metrics['undercount_sets']}")
    print(f" Overcount Sets       : {metrics['overcount_sets']}")
    print(f" Mean Absolute Error  : {metrics['mae']:.2f} reps")
    print("=" * 60)


if __name__ == "__main__":
    out_file = sys.argv[1] if len(sys.argv) > 1 else "dataset_analysis.png"
    generate_dashboard(out_file)
