#!/usr/bin/env python3
"""
detect_pushups.py

Diagnostic visualizer for the Garmin Push-Up Counter FIT data.
Mirrors the 3-row diagnostic layout of PullUp/detect_pullups.py while modeling
true push-up biomechanics from the 3-axis wrist accelerometer:

Physics of a Push-Up on the Wrist Accelerometer:
  1. Top of Plank (straight arms, hands on floor):
     - Forearm is vertical -> X-axis carries ~1G (+880 to +1000 mG).
     - Y-axis (wrist lateral/tilt) is flat (~+50 to +200 mG).
  2. Lowering Chest (eccentric phase -> bottom of push-up):
     - Forearm tilts forward as elbows bend -> gravity shifts into Y-axis (+500 to +650 mG)
       while X-axis dips (+700 to +800 mG).
  3. Pushing Up (concentric phase -> elbow lockout):
     - Forearm returns vertical -> Y-axis drops back below +240 mG and X-axis
       recovers above +840 mG.
  4. Start / End Floor Impacts:
     - Planting hands on the floor (start) and pushing off the floor to stand up (end)
       produce sharp high-G impact spikes (Magnitude >= 1600 mG) without a valid
       sustained plank-tilt-plank cycle.

Usage:
    python detect_pushups.py <path/to/file.fit>
    python detect_pushups.py 24760030440.fit          # searches data/ folder
"""

import os
import sys
from typing import Optional, Tuple, List, Dict, Any

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

try:
    import fitdecode
except ImportError:
    sys.exit("Error: 'fitdecode' is required. Install with: pip install fitdecode")


# ---------------------------------------------------------------------------
# Detector configuration — tuned for push-up forearm tilt biomechanics.
# ---------------------------------------------------------------------------
DETECTOR_CONFIG: Dict[str, Any] = {
    "window_size":               25,    # samples (0.25s) — causal smoothing window for X and Y tilt
    "rep_threshold":            320,    # mG — Y_smooth threshold to enter bottom-of-pushup (ARMED)
    "reset_threshold":          240,    # mG — Y_smooth return threshold at top-of-plank lockout
    "x_lockout_min":            800,    # mG — minimum X_smooth required at top-of-plank rep completion
    "x_plank_min":              620,    # mG — minimum X_smooth required throughout a valid push-up wave
    "x_settle_min":             800,    # mG — minimum X_smooth to confirm stable top-of-plank mount
    "y_settle_max":             220,    # mG — maximum Y_smooth to confirm stable top-of-plank mount
    "settle_streak_req":         40,    # samples (0.40s) of quiet top-of-plank required after hand-plant
    "impact_mag_threshold":    1600,    # mG — floor hand-plant / push-off impact spike level
    "x_release_threshold":      450,    # mG — X below this = left plank position
    "x_latch_streak_len":        35,    # samples (0.35s) continuous departure to lock set
    "min_wave_duration":         20,    # samples (0.20s) — minimum duration of a fast push-up cycle
    "debounce_min":              65,    # samples (0.65s) — minimum interval between confirmed reps
    "debounce_max":             110,    # samples (1.10s) — maximum adaptive debounce
}


# ---------------------------------------------------------------------------
# 1. FIT Data Extraction
# ---------------------------------------------------------------------------

def extract_high_freq_accel(fit_path: str) -> Optional[pd.DataFrame]:
    """
    Reads calibrated 100 Hz accelerometer data from a FIT file.
    Returns DataFrame with columns ['x', 'y', 'z', 'magnitude'], or None.
    """
    x_vals, y_vals, z_vals = [], [], []

    try:
        with fitdecode.FitReader(fit_path) as fit:
            for frame in fit:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue
                if frame.name not in ("accelerometer_data", "sensor_data"):
                    continue

                def _get(axis: str):
                    for name in (f"calibrated_accel_{axis}", f"accel_{axis}", axis):
                        if frame.has_field(name):
                            return frame.get_value(name)
                    return None

                x, y, z = _get("x"), _get("y"), _get("z")
                if x is None or y is None or z is None:
                    continue

                if isinstance(x, (list, tuple, np.ndarray)):
                    x_vals.extend(x)
                    y_vals.extend(y)
                    z_vals.extend(z)
                else:
                    x_vals.append(x)
                    y_vals.append(y)
                    z_vals.append(z)

    except Exception as exc:
        print(f"Warning: error reading '{fit_path}': {exc}")
        return None

    if not x_vals:
        return None

    df = pd.DataFrame({"x": x_vals, "y": y_vals, "z": z_vals})
    sq_sum = df["x"].astype(float) ** 2 + df["y"].astype(float) ** 2 + df["z"].astype(float) ** 2
    df["magnitude"] = np.sqrt(sq_sum)
    return df


def extract_fit_session_reps(fit_path: str) -> Optional[int]:
    """
    Reads the recorded rep count from FIT session/lap developer fields.
    """
    try:
        with fitdecode.FitReader(fit_path) as fit:
            for frame in fit:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue
                if frame.name not in ("session", "lap"):
                    continue

                for field in frame.fields:
                    if (
                        field.name
                        and "rep" in field.name.lower()
                        and "unconfirmed" not in field.name.lower()
                        and field.value is not None
                        and isinstance(field.value, (int, float))
                    ):
                        return int(field.value)

                if hasattr(frame, "dev_fields"):
                    for dev_field in frame.dev_fields:
                        name = (dev_field.name or "").lower()
                        if "rep" in name and dev_field.value is not None:
                            try:
                                return int(dev_field.value)
                            except (TypeError, ValueError):
                                pass

    except Exception:
        pass
    return None


def extract_true_reps(fit_path: str) -> Optional[int]:
    """
    Returns the ground-truth rep count for a FIT file.
    """
    fname = os.path.basename(fit_path)
    manual_labels: Dict[str, int] = {}
    if fname in manual_labels:
        return manual_labels[fname]
    return extract_fit_session_reps(fit_path)


def resolve_fit_path(arg_path: str) -> str:
    """
    Resolves a FIT file argument to an actual file path,
    checking the working directory and the data/ subfolder.
    Supports:
      - Negative indices (e.g. '-1' for the latest file, '-2' for second latest)
      - Partial names / activity IDs (e.g. '24760030440')
      - Direct relative or absolute file paths
    """
    # Check for negative index (e.g., -1, -2, etc.)
    try:
        idx = int(arg_path)
        if idx < 0 and os.path.isdir("data"):
            fit_files = sorted([
                f for f in os.listdir("data")
                if f.endswith(".fit")
            ])
            if fit_files and abs(idx) <= len(fit_files):
                return os.path.join("data", fit_files[idx])
    except ValueError:
        pass

    if os.path.isfile(arg_path):
        return arg_path
    candidate = os.path.join("data", arg_path)
    if os.path.isfile(candidate):
        return candidate
    
    # Try substring match in data/ directory
    if os.path.isdir("data"):
        for f in os.listdir("data"):
            if f.endswith(".fit") and arg_path in f:
                return os.path.join("data", f)
                
    return arg_path


# ---------------------------------------------------------------------------
# 2. Causal Smoothing (O(1) Circular Buffer Arithmetic)
# ---------------------------------------------------------------------------

def precompute_smoothed_axes(
    x: np.ndarray,
    y: np.ndarray,
    window_size: int = 25,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Computes causal moving averages of X and Y axes using integer arithmetic,
    matching O(1) circular buffers in Monkey C.
    """
    n = len(x)
    x_buf = [0] * window_size
    y_buf = [0] * window_size
    buf_idx = 0
    x_sum = 0
    y_sum = 0

    x_smooth = np.zeros(n, dtype=np.int32)
    y_smooth = np.zeros(n, dtype=np.int32)

    for i in range(n):
        x_sum -= x_buf[buf_idx]
        y_sum -= y_buf[buf_idx]

        xi = int(x[i])
        yi = int(y[i])
        x_buf[buf_idx] = xi
        y_buf[buf_idx] = yi

        x_sum += xi
        y_sum += yi
        buf_idx = (buf_idx + 1) % window_size

        count = i + 1 if i + 1 < window_size else window_size
        x_smooth[i] = x_sum // count
        y_smooth[i] = y_sum // count

    return x_smooth, y_smooth


# ---------------------------------------------------------------------------
# 3. Push-Up Forearm-Tilt Detector Simulation with Full Trace
# ---------------------------------------------------------------------------

def simulate_with_trace(
    x_smooth: np.ndarray,
    y_smooth: np.ndarray,
    mags: np.ndarray,
    x_raw: np.ndarray,
    config: Dict[str, Any],
) -> Tuple[
    List[int],      # confirmed_reps (sample index of rep completion / lockout)
    List[int],      # rep_peaks (sample index of bottom-of-pushup peak for each confirmed rep)
    List[int],      # cancelled_reps
    List[int],      # narrow_reps
    Optional[int],  # mount_idx
    Optional[int],  # dismount_idx
    Optional[int],  # settle_idx
    np.ndarray,     # rep_thresh_history
    np.ndarray,     # reset_thresh_history
]:
    """
    Simulates the online Push-Up Detector using the Forearm Tilt (Y_smooth & X_smooth)
    pattern and floor impact guards:

      State -1 (STATE_MOUNT_SETTLING):
        Wait for user to get into straight-arm plank (X_smooth >= 800 mG,
        Y_smooth <= 220 mG, Magnitude < 1600 mG) for >= 40 samples (0.40s).
        Any floor hand-plant impact (Magnitude >= 1600 mG) while mounting resets
        the settling counter so getting into position never counts as a rep.

      State 0 (STATE_READY_TO_ARM):
        In plank position. When the user lowers their body, the forearm tilts and
        Y_smooth rises above cur_rep_threshold (~380 mG) while X_smooth stays in plank
        (>= 620 mG). Transitions to STATE_ARMED.

      State 1 (STATE_ARMED — Descending / At Bottom of Push-Up):
        Tracks the peak forearm tilt (max Y_smooth) and minimum X_smooth.
        If a floor/dismount impact spike (Magnitude >= 1600 mG) or plank departure
        (X_smooth < 620 mG) occurs, cancels the wave immediately.
        When the user pushes back up to straight-arm lockout (Y_smooth <= cur_reset_threshold
        AND X_smooth >= x_lockout_min), validates wave duration (>= min_wave_duration)
        and confirms the rep!
    """
    rep_th = config["rep_threshold"]
    reset_th = config["reset_threshold"]
    x_lockout_min = config["x_lockout_min"]
    x_plank_min = config["x_plank_min"]
    x_settle_min = config["x_settle_min"]
    y_settle_max = config["y_settle_max"]
    settle_streak_req = config["settle_streak_req"]
    impact_mag_th = config["impact_mag_threshold"]
    x_release_th = config["x_release_threshold"]
    x_latch_streak = config["x_latch_streak_len"]
    min_wave_duration = config["min_wave_duration"]
    deb_min = config["debounce_min"]
    deb_max = config["debounce_max"]

    n_samples = len(y_smooth)
    state = -1  # -1 = SETTLING, 0 = READY_TO_ARM, 1 = ARMED (in push-up rep)

    cur_rep_threshold = rep_th
    cur_reset_threshold = reset_th
    peak_avg = 580.0
    debounce_cur = deb_min
    samples_since_last = deb_min

    confirmed_reps: List[int] = []
    rep_peaks: List[int] = []
    cancelled_reps: List[int] = []
    narrow_reps: List[int] = []

    has_mounted = False
    mount_streak = 0
    settle_streak = 0
    mount_idx: Optional[int] = None
    settle_idx: Optional[int] = None
    dismount_idx: Optional[int] = None
    last_impact_idx: Optional[int] = None
    release_streak = 0
    set_locked = False

    wave_start = 0
    wave_peak_y = 0
    wave_peak_idx = 0

    rep_thresh_history = np.zeros(n_samples, dtype=np.int32)
    reset_thresh_history = np.zeros(n_samples, dtype=np.int32)

    has_settled = False

    for i in range(n_samples):
        rep_thresh_history[i] = cur_rep_threshold
        reset_thresh_history[i] = cur_reset_threshold

        if set_locked:
            continue

        cx = int(x_smooth[i])
        cy = int(y_smooth[i])
        cmag = int(mags[i])
        raw_x = int(x_raw[i])

        samples_since_last += 1

        # --- 1. Detect initial entry into plank orientation ---
        if not has_mounted:
            if raw_x >= x_release_th:
                mount_streak += 1
                if mount_streak >= 25:
                    has_mounted = True
                    mount_idx = i - 25 + 1
            else:
                mount_streak = 0

        # --- 2. Floor impact spike guard (hand-plant at start / push-off at end) ---
        if cmag >= impact_mag_th:
            last_impact_idx = i
            if not has_settled:
                # Hand-plant impact while getting into position -> stay in / return to SETTLING
                state = -1
                settle_streak = 0
                settle_idx = None
                continue

        # --- 3. Plank departure / set termination latch ---
        if has_mounted and state != -1:
            if raw_x < x_release_th or cx < x_release_th:
                release_streak += 1
            else:
                release_streak = 0

            if release_streak >= x_latch_streak:
                set_locked = True
                departure_start = i - x_latch_streak
                # If a push-off impact occurred right before departure, mark dismount at that push-off
                if last_impact_idx is not None and (departure_start - last_impact_idx) <= 100:
                    dismount_idx = last_impact_idx
                else:
                    dismount_idx = departure_start

                if state == 1:
                    cancelled_reps.append(wave_peak_idx)
                    state = 0
                continue

        # --- 4. FSM Transitions ---
        if state == -1:  # STATE_MOUNT_SETTLING
            # Require sustained, quiet straight-arm plank (X_smooth >= 800, Y_smooth <= 220)
            if has_mounted and cx >= x_settle_min and cy <= y_settle_max and cmag < 1400:
                settle_streak += 1
                if settle_streak >= settle_streak_req:
                    state = 0  # -> STATE_READY_TO_ARM
                    has_settled = True
                    settle_idx = i
            else:
                settle_streak = 0

        elif state == 0:  # STATE_READY_TO_ARM
            # If user drops out of plank while waiting, ignore
            if cx < x_plank_min:
                continue

            # Start of push-up descent: Y_smooth rises above cur_rep_threshold
            if cy >= cur_rep_threshold:
                state = 1  # -> STATE_ARMED
                wave_start = i
                wave_peak_y = cy
                wave_peak_idx = i

        elif state == 1:  # STATE_ARMED (lowering & pushing back up)
            # Track maximum forearm tilt (bottom of push-up)
            if cy > wave_peak_y:
                wave_peak_y = cy
                wave_peak_idx = i

            # If X_smooth collapses below plank minimum during wave, user broke plank (getting up)
            if cx < x_plank_min:
                cancelled_reps.append(wave_peak_idx)
                state = 0
                continue

            # Rep completion: forearm returns to vertical top-of-plank lockout
            if cy <= cur_reset_threshold and cx >= x_lockout_min:
                wave_dur = i - wave_start
                peak_gap = (wave_peak_idx - rep_peaks[-1]) if rep_peaks else deb_min
                if wave_dur >= min_wave_duration and peak_gap >= debounce_cur:
                    # Confirm rep!
                    if rep_peaks:
                        dt_prev = wave_peak_idx - rep_peaks[-1]
                        debounce_cur = min(deb_max, max(deb_min, int(0.55 * dt_prev)))
                    else:
                        debounce_cur = deb_min

                    confirmed_reps.append(i)
                    rep_peaks.append(wave_peak_idx)
                    samples_since_last = 0

                    # Adaptive threshold update for deep fatigue sets
                    if len(confirmed_reps) >= 4:
                        peak_avg = 0.30 * float(wave_peak_y) + 0.70 * peak_avg
                        cur_rep_threshold = max(280, min(420, int(0.65 * peak_avg)))
                        cur_reset_threshold = max(200, min(260, int(0.62 * cur_rep_threshold)))
                else:
                    narrow_reps.append(wave_peak_idx)

                state = 0  # -> STATE_READY_TO_ARM

    return (
        confirmed_reps,
        rep_peaks,
        cancelled_reps,
        narrow_reps,
        mount_idx,
        dismount_idx,
        settle_idx,
        rep_thresh_history,
        reset_thresh_history,
    )


# ---------------------------------------------------------------------------
# 4. Top-level Detector Runner
# ---------------------------------------------------------------------------

def simulate_pushup_detector(df: pd.DataFrame) -> tuple:
    """
    Runs the canonical push-up forearm-tilt detection algorithm on a DataFrame
    from extract_high_freq_accel().
    """
    x_raw = df["x"].values.astype(np.int32)
    y_raw = df["y"].values.astype(np.int32)
    z_raw = df["z"].values.astype(np.int32)

    sq_sums = (
        x_raw.astype(np.int64) ** 2
        + y_raw.astype(np.int64) ** 2
        + z_raw.astype(np.int64) ** 2
    )
    mags = np.sqrt(sq_sums).astype(np.int32)

    x_smooth, y_smooth = precompute_smoothed_axes(
        x_raw, y_raw, window_size=DETECTOR_CONFIG["window_size"]
    )

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
    ) = simulate_with_trace(x_smooth, y_smooth, mags, x_raw, DETECTOR_CONFIG)

    return (
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
    )


# ---------------------------------------------------------------------------
# 5. Diagnostic 3-Row Plot
# ---------------------------------------------------------------------------

def plot_pushup_inspection(
    df: pd.DataFrame,
    fname: str,
    confirmed: list,
    rep_peaks: list,
    cancelled: list,
    narrow: list,
    mount_idx: Optional[int],
    dismount_idx: Optional[int],
    settle_idx: Optional[int],
    rep_th_hist: np.ndarray,
    reset_th_hist: np.ndarray,
    x_smooth: np.ndarray,
    y_smooth: np.ndarray,
    true_reps: Optional[int],
    fs: float = 100.0,
) -> None:
    """
    Renders a 3-row stacked diagnostic figure:
      Row 1: Raw Acceleration Magnitude & Floor Impact Guard
      Row 2: Causal Forearm Tilt Signal (Y_smooth & X_smooth) & Rep Detections
      Row 3: Raw 3-Axis Acceleration Components (Directional Orientation & Gravity)
    """
    x = df["x"].values.astype(np.float64)
    y = df["y"].values.astype(np.float64)
    z = df["z"].values.astype(np.float64)
    sq_sums = (
        df["x"].values.astype(np.int64) ** 2
        + df["y"].values.astype(np.int64) ** 2
        + df["z"].values.astype(np.int64) ** 2
    )
    mags = np.sqrt(sq_sums).astype(np.int32)

    n_samples = len(mags)
    duration_s = n_samples / fs
    time_s = np.arange(n_samples) / fs

    det_reps = len(confirmed)

    if true_reps is not None:
        error = det_reps - true_reps
        if error == 0:
            title_color = "#155724"
            bg_badge = "EXACT MATCH"
        elif error > 0:
            title_color = "#004085"
            bg_badge = f"OVERCOUNT (+{error})"
        else:
            title_color = "#721c24"
            bg_badge = f"UNDERCOUNT ({error})"
        sign = "+" if error > 0 else ""
        rep_summary_str = f"True: {true_reps}  |  Detected: {det_reps} ({sign}{error})"
    else:
        title_color = "#2c3e50"
        bg_badge = "UNLABELED"
        rep_summary_str = f"Detected: {det_reps} Reps"

    mount_str = (
        f"Plank: {mount_idx / fs:.2f}s (Settled: {settle_idx / fs:.2f}s)"
        if (mount_idx is not None and settle_idx is not None)
        else (f"Plank: {mount_idx / fs:.2f}s" if mount_idx is not None else "Plank: N/A")
    )
    dismount_str = (
        f"Left Plank: {dismount_idx / fs:.2f}s"
        if dismount_idx is not None
        else "Left Plank: End"
    )

    fig, axes = plt.subplots(3, 1, figsize=(16, 11), sharex=True, dpi=120)

    fig.suptitle(
        (
            f"{fname}  |  {rep_summary_str}  |  Dur: {duration_s:.1f}s"
            f"  [{bg_badge}]  |  {mount_str} -> {dismount_str}"
        ),
        fontsize=13,
        fontweight="bold",
        color=title_color,
        y=0.98,
    )

    # --- Plank entry / exit boundary lines across all subplots ---
    for ax in axes:
        if settle_idx is not None:
            t_s = settle_idx / fs
            ax.axvline(
                t_s,
                color="purple",
                linestyle="--",
                lw=1.5,
                alpha=0.9,
                label=f"Plank Settled ({t_s:.2f}s)" if ax is axes[0] else "",
            )
        if dismount_idx is not None:
            t_d = dismount_idx / fs
            ax.axvline(
                t_d,
                color="purple",
                linestyle="--",
                lw=1.5,
                alpha=0.9,
                label=f"Left Plank ({t_d:.2f}s)" if ax is axes[0] else "",
            )
            ax.axvspan(
                t_d,
                duration_s,
                color="purple",
                alpha=0.08,
                label="Post-Workout Latch Lockout" if ax is axes[1] else "",
            )

    # -------------------------------------------------------------------------
    # Subplot 1 (Top): Raw Acceleration Magnitude & Floor Impact Guard
    # -------------------------------------------------------------------------
    axes[0].plot(time_s, mags, color="#2c3e50", lw=0.8, alpha=0.85, label="Raw Magnitude (mG)")
    axes[0].axhline(1000, color="gray", linestyle=":", lw=0.9, alpha=0.7, label="1G Static Level (1000 mG)")
    axes[0].axhline(
        DETECTOR_CONFIG["impact_mag_threshold"],
        color="#800080",
        linestyle=":",
        lw=1.1,
        alpha=0.7,
        label=f"Floor Impact Guard ({DETECTOR_CONFIG['impact_mag_threshold']} mG)",
    )

    for p_samp in rep_peaks:
        axes[0].axvline(p_samp / fs, color="crimson", linestyle="--", lw=1.1, alpha=0.8)
    for c_samp in cancelled:
        axes[0].axvline(c_samp / fs, color="darkorange", linestyle="-.", lw=1.4, alpha=0.9)
    for n_samp in narrow:
        axes[0].axvline(n_samp / fs, color="gray", linestyle=":", lw=1.4, alpha=0.9)

    axes[0].set_ylabel("Magnitude (mG)", fontsize=10, fontweight="bold")
    axes[0].set_title("1. Acceleration Magnitude & Floor Impact Rejection", fontsize=11, fontweight="bold")
    axes[0].set_ylim(0, max(2600, int(np.max(mags)) + 200))
    axes[0].grid(True, linestyle=":", alpha=0.5)
    axes[0].legend(loc="upper right", fontsize=8, ncol=4)

    # -------------------------------------------------------------------------
    # Subplot 2 (Middle): Causal Forearm Tilt Signal (Y_smooth & X_smooth)
    # -------------------------------------------------------------------------
    axes[1].plot(
        time_s,
        y_smooth,
        color="#2ca02c",
        lw=1.6,
        label=f"Smoothed Y-Axis Forearm Tilt ({DETECTOR_CONFIG['window_size']}-sample MA)",
    )
    axes[1].plot(
        time_s,
        x_smooth,
        color="#1f77b4",
        lw=1.1,
        alpha=0.6,
        label=f"Smoothed X-Axis Plank Support ({DETECTOR_CONFIG['window_size']}-sample MA)",
    )
    axes[1].plot(
        time_s,
        rep_th_hist,
        color="crimson",
        linestyle="-",
        lw=1.3,
        label=f"Bottom-of-Rep Tilt Threshold ({DETECTOR_CONFIG['rep_threshold']} mG)",
    )
    axes[1].plot(
        time_s,
        reset_th_hist,
        color="forestgreen",
        linestyle="--",
        lw=1.3,
        label=f"Top-of-Plank Lockout Threshold ({DETECTOR_CONFIG['reset_threshold']} mG)",
    )

    # Mount settling shading (covers initial descent & hand-plant shock)
    if settle_idx is not None:
        t_settle = settle_idx / fs
        axes[1].axvspan(
            0,
            t_settle,
            color="gray",
            alpha=0.18,
            label=f"Getting Into Plank / Settling (0 -> {t_settle:.2f}s)",
        )

    # Label Confirmed Reps at their bottom-of-pushup tilt peak
    for r_i, (p_samp, c_samp) in enumerate(zip(rep_peaks, confirmed), 1):
        t_peak = p_samp / fs
        t_conf = c_samp / fs
        peak_val = y_smooth[p_samp]
        axes[1].axvline(t_peak, color="crimson", linestyle="--", lw=1.1, alpha=0.85)
        axes[1].plot(t_peak, peak_val, marker="o", markersize=6, color="crimson", zorder=5)
        axes[1].plot(t_conf, y_smooth[c_samp], marker="^", markersize=5, color="forestgreen", zorder=5)
        axes[1].text(
            t_peak,
            peak_val + 25,
            f"#{r_i}",
            ha="center",
            va="bottom",
            fontsize=8,
            fontweight="bold",
            color="crimson",
        )

    # Cancelled waves
    for c_samp in cancelled:
        t_c = c_samp / fs
        val = y_smooth[c_samp]
        axes[1].axvline(t_c, color="darkorange", linestyle="-.", lw=1.4, alpha=0.9)
        axes[1].plot(t_c, val, marker="x", markersize=8, color="darkorange", markeredgewidth=2, zorder=5)
        axes[1].text(
            t_c, val + 25, "CANC",
            ha="center", va="bottom", fontsize=8, fontweight="bold", color="darkorange",
        )

    # Narrow / twitch rejections
    for n_samp in narrow:
        t_n = n_samp / fs
        val = y_smooth[n_samp]
        axes[1].axvline(t_n, color="gray", linestyle=":", lw=1.4, alpha=0.9)
        axes[1].plot(t_n, val, marker="v", markersize=7, color="gray", zorder=5)
        axes[1].text(
            t_n, val + 25, "TWITCH",
            ha="center", va="bottom", fontsize=8, fontweight="bold", color="gray",
        )

    axes[1].set_ylabel("Smoothed Tilt (mG)", fontsize=10, fontweight="bold")
    axes[1].set_title(
        "2. Causal Forearm Tilt Wave (Green = Y Tilt Peak on Descent, Blue = X Plank Support)",
        fontsize=11,
        fontweight="bold",
    )
    axes[1].set_ylim(-400, 1300)
    axes[1].grid(True, linestyle=":", alpha=0.5)
    axes[1].legend(loc="upper right", fontsize=8, ncol=3)

    # -------------------------------------------------------------------------
    # Subplot 3 (Bottom): Raw 3-Axis Components (Orientation & Gravity)
    # -------------------------------------------------------------------------
    axes[2].plot(time_s, x, color="#1f77b4", lw=0.9, alpha=0.85, label="X-axis (forearm long axis — PLANK support)")
    axes[2].plot(time_s, y, color="#2ca02c", lw=0.9, alpha=0.85, label="Y-axis (forearm tilt — PUSH-UP wave)")
    axes[2].plot(time_s, z, color="#d62728", lw=0.9, alpha=0.85, label="Z-axis (dorsal / perpendicular)")
    axes[2].axhline(0, color="gray", linestyle=":", lw=0.8)
    axes[2].axhline(
        +1000, color="#1f77b4", linestyle="--", lw=0.8, alpha=0.6,
        label="+1G Plank Level (X ≈ +1000 mG)"
    )
    axes[2].axhline(
        DETECTOR_CONFIG["x_release_threshold"],
        color="purple",
        linestyle=":",
        lw=1.1,
        alpha=0.8,
        label=f"Plank Release Level ({DETECTOR_CONFIG['x_release_threshold']} mG)",
    )

    axes[2].set_xlabel("Time (seconds)", fontsize=10, fontweight="bold")
    axes[2].set_ylabel("Acceleration (mG)", fontsize=10, fontweight="bold")
    axes[2].set_title(
        "3. Raw 3-Axis Acceleration Components (Directional Orientation & Gravity)",
        fontsize=11,
        fontweight="bold",
    )
    axes[2].grid(True, linestyle=":", alpha=0.5)
    axes[2].set_xlim(0, duration_s)
    axes[2].legend(loc="upper right", fontsize=8, ncol=4)

    plt.tight_layout(rect=[0, 0.02, 1, 0.96])
    plt.show()


# ---------------------------------------------------------------------------
# 6. Summary Stats (printed to console)
# ---------------------------------------------------------------------------

def print_summary(
    fit_path: str,
    df: pd.DataFrame,
    confirmed: list,
    rep_peaks: list,
    cancelled: list,
    narrow: list,
    mount_idx: Optional[int],
    dismount_idx: Optional[int],
    settle_idx: Optional[int],
    true_reps: Optional[int],
    fs: float = 100.0,
) -> None:
    fname = os.path.basename(fit_path)
    det_reps = len(confirmed)

    print("=" * 60)
    print(f"File     : {fname}")
    print(f"Samples  : {len(df)}  ({len(df) / fs:.1f}s @ {fs:.0f} Hz)")
    print(f"Detected : {det_reps} reps  |  True: {true_reps if true_reps is not None else 'Unknown'}")

    if true_reps is not None:
        error = det_reps - true_reps
        sign = "+" if error >= 0 else ""
        print(f"Error    : {sign}{error}  ({'MATCH' if error == 0 else 'OVER' if error > 0 else 'UNDER'})")

    if mount_idx is not None:
        settle_str = f"  Settled: {settle_idx / fs:.2f}s" if settle_idx is not None else ""
        print(f"Plank    : {mount_idx / fs:.2f}s{settle_str}")
    else:
        print("Plank    : Not detected")

    if dismount_idx is not None:
        print(f"Left     : {dismount_idx / fs:.2f}s")

    if rep_peaks:
        peak_times = ", ".join(f"{p / fs:.2f}s" for p in rep_peaks)
        print(f"Rep Peaks: [{peak_times}]")
    if cancelled:
        print(f"Cancelled: {len(cancelled)} at samples {cancelled}")
    if narrow:
        print(f"Twitches : {len(narrow)} at samples {narrow}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# 7. Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    raw_arg = sys.argv[1] if len(sys.argv) > 1 else "-1"
    fit_path = resolve_fit_path(raw_arg)

    if not os.path.isfile(fit_path):
        print(f"Error: FIT file not found: '{fit_path}'")
        print("Usage: python detect_pushups.py <file.fit>")
        sys.exit(1)

    df = extract_high_freq_accel(fit_path)
    if df is None or len(df) == 0:
        print(f"Could not load accelerometer data from '{fit_path}'.")
        sys.exit(1)

    fname = os.path.basename(fit_path)
    true_reps = extract_true_reps(fit_path)

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

    print_summary(
        fit_path=fit_path,
        df=df,
        confirmed=confirmed,
        rep_peaks=rep_peaks,
        cancelled=cancelled,
        narrow=narrow,
        mount_idx=mount_idx,
        dismount_idx=dismount_idx,
        settle_idx=settle_idx,
        true_reps=true_reps,
    )

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
    )


if __name__ == "__main__":
    main()
