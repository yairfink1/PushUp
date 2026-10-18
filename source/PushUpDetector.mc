import Toybox.Lang;
import Toybox.Math;
import Toybox.System;

// ---------------------------------------------------------------------------
// PushUpDetector - reusable, online repetition detection engine for push-ups.
//
// Physics of a Push-Up on the Wrist Accelerometer:
//   1. Top of Plank (straight arms, hands planted on floor):
//      - Forearm is vertical -> X-axis carries ~1G (+880 to +1000 mG).
//      - Y-axis (forearm tilt) is flat (~+50 to +200 mG).
//   2. Lowering Chest (eccentric phase -> bottom of push-up):
//      - Forearm tilts forward as elbows bend -> gravity shifts into Y-axis
//        (+500 to +650 mG) while X-axis dips (+700 to +800 mG).
//   3. Pushing Up (concentric phase -> elbow lockout):
//      - Forearm returns vertical -> Y-axis drops back below +240 mG and
//        X-axis recovers above +840 mG.
//   4. Start / End Floor Impacts:
//      - Planting hands on the floor (start) and pushing off the floor to
//        stand up (end) produce sharp high-G impact spikes (Magnitude >= 1600 mG)
//        without a valid sustained plank-tilt-plank cycle.
//
// Signal processing:
//   - Causal 25-sample (0.25s) moving averages of X and Y axes (xSmooth, ySmooth)
//     computed in O(1) time via circular buffers.
//   - Raw 3D vector magnitude = sqrt(x^2 + y^2 + z^2) [mG] for impact rejection.
//
// Finite State Machine:
//   State -1 (STATE_MOUNT_SETTLING):
//     Wait for user to stabilize in straight-arm top-of-plank (xSmooth >= 800 mG,
//     ySmooth <= 220 mG, mag < 1400 mG) for >= 0.40s. Any floor hand-plant impact
//     (mag >= 1600 mG) before the first rep resets settling so getting into
//     position never triggers a false rep.
//   State  0 (STATE_READY_TO_ARM):
//     In plank position. Arms into STATE_ARMED when forearm tilts on descent
//     (ySmooth >= curRepThreshold while xSmooth >= 620 mG).
//   State  1 (STATE_ARMED):
//     Tracks bottom-of-pushup tilt peak (max ySmooth). Cancels immediately if
//     plank breaks (xSmooth < 620 mG) or floor push-off impact occurs (mag >= 1600 mG).
//     Confirms rep when user returns to top-of-plank lockout (ySmooth <= curResetThreshold
//     AND xSmooth >= 840 mG) after >= minWaveDuration (0.65s) and peak-to-peak debounce.
// ---------------------------------------------------------------------------

const STATE_MOUNT_SETTLING as Number = -1;
const STATE_READY_TO_ARM   as Number = 0;
const STATE_ARMED          as Number = 1;
const STATE_COOLDOWN       as Number = 2;

class PushUpDetector {

    // Smoothing window size (0.25s at 100 Hz).
    private const WINDOW_SIZE          as Number = 25;

    // Forearm tilt & plank posture thresholds (in mG).
    private const BASE_REP_THRESHOLD   as Number = 380;  // Y_smooth threshold to enter bottom-of-rep
    private const BASE_RESET_THRESHOLD as Number = 250;  // Y_smooth return threshold at top-of-plank lockout
    private const X_LOCKOUT_MIN        as Number = 800;  // Min X_smooth required at top-of-plank lockout
    private const X_PLANK_MIN          as Number = 620;  // Min X_smooth required throughout a valid wave
    private const X_SETTLE_MIN         as Number = 800;  // Min X_smooth to confirm stable top-of-plank mount
    private const Y_SETTLE_MAX         as Number = 220;  // Max Y_smooth to confirm stable top-of-plank mount
    private const SETTLE_MAG_MAX       as Number = 1400; // Max magnitude allowed during quiet plank settling
    private const IMPACT_MAG_THRESHOLD as Number = 1600; // Floor hand-plant / push-off impact spike level
    private const X_RELEASE_THRESHOLD  as Number = 450;  // X below this = left plank position

    // Sample rate scaling.
    private var _sampleRate as Number = 100;

    // Scaled sample thresholds (calibrated to 100 Hz baseline).
    private var _mountStreakReq   as Number = 25;  // 0.25s initial plank orientation entry
    private var _settleStreakReq  as Number = 40;  // 0.40s quiet straight-arm plank settling
    private var _xLatchStreakLen  as Number = 35;  // 0.35s continuous departure to lock set
    private var _minWaveDuration  as Number = 25;  // 0.25s minimum push-up wave duration
    private var _debounceMin      as Number = 65;  // 0.65s minimum peak-to-peak interval
    private var _debounceMax      as Number = 110; // 1.10s maximum adaptive debounce

    // Circular buffers for O(1) causal moving average of X and Y axes.
    private var _xBuf     as Array<Number>;
    private var _yBuf     as Array<Number>;
    private var _bufIdx   as Number = 0;
    private var _bufCount as Number = 0;
    private var _xSum     as Number = 0;
    private var _ySum     as Number = 0;

    // Counters and state.
    private var _repCount      as Number = 0;
    private var _sampleCount   as Number = 0;
    private var _state         as Number = STATE_MOUNT_SETTLING;

    // Plank mount, settling, and release guard state.
    private var _hasMounted    as Boolean = false;
    private var _hasSettled    as Boolean = false;
    private var _mountStreak   as Number = 0;
    private var _settleStreak  as Number = 0;
    private var _releaseStreak as Number = 0;
    private var _isSetLocked   as Boolean = false;

    // Active push-up wave tracking.
    private var _waveStartSample as Number = 0;
    private var _wavePeakY       as Number = 0;
    private var _wavePeakIdx     as Number = 0;
    private var _lastRepPeakIdx  as Number = -1;

    // Adaptive threshold state for deep fatigue sets.
    private var _curDebounce       as Number = 65;
    private var _curRepThreshold   as Number = 380;
    private var _curResetThreshold as Number = 250;
    private var _peakAvg           as Float = 580.0;

    function initialize() {
        _xBuf = new Array<Number>[WINDOW_SIZE];
        _yBuf = new Array<Number>[WINDOW_SIZE];
        reset();
    }

    // Configure sample rate and scale timing parameters relative to 100 Hz.
    public function start(sampleRate as Number) as Void {
        _sampleRate = (sampleRate > 0) ? sampleRate : 100;
        var rateScale = _sampleRate.toFloat() / 100.0;

        _mountStreakReq = (25 * rateScale).toNumber();
        if (_mountStreakReq < 3) { _mountStreakReq = 3; }

        _settleStreakReq = (40 * rateScale).toNumber();
        if (_settleStreakReq < 5) { _settleStreakReq = 5; }

        _xLatchStreakLen = (35 * rateScale).toNumber();
        if (_xLatchStreakLen < 3) { _xLatchStreakLen = 3; }

        _minWaveDuration = (25 * rateScale).toNumber();
        if (_minWaveDuration < 5) { _minWaveDuration = 5; }

        _debounceMin = (65 * rateScale).toNumber();
        if (_debounceMin < 5) { _debounceMin = 5; }

        _debounceMax = (110 * rateScale).toNumber();
        if (_debounceMax < 10) { _debounceMax = 10; }

        reset();
    }

    // Reset all internal state for a new set.
    public function reset() as Void {
        _sampleCount   = 0;
        _repCount      = 0;
        _bufIdx        = 0;
        _bufCount      = 0;
        _xSum          = 0;
        _ySum          = 0;

        _state         = STATE_MOUNT_SETTLING;
        _hasMounted    = false;
        _hasSettled    = false;
        _mountStreak   = 0;
        _settleStreak  = 0;
        _releaseStreak = 0;
        _isSetLocked   = false;

        _waveStartSample = 0;
        _wavePeakY       = 0;
        _wavePeakIdx     = 0;
        _lastRepPeakIdx  = -1;

        _curDebounce       = _debounceMin;
        _curRepThreshold   = BASE_REP_THRESHOLD;
        _curResetThreshold = BASE_RESET_THRESHOLD;
        _peakAvg           = 580.0;

        for (var i = 0; i < WINDOW_SIZE; i++) {
            _xBuf[i] = 0;
            _yBuf[i] = 0;
        }
    }

    // Processes a single 3-axis accelerometer sample (in mG).
    // Returns:
    //   1 : Repetition was confirmed at top-of-plank lockout
    //   0 : Normal sample, no change in rep count
    public function processSample(x as Number, y as Number, z as Number) as Number {
        if (_isSetLocked) {
            return 0;
        }

        var curSampleIdx = _sampleCount;
        _sampleCount++;

        // 1. Update causal moving averages for X and Y in O(1).
        _xSum -= _xBuf[_bufIdx];
        _ySum -= _yBuf[_bufIdx];
        _xBuf[_bufIdx] = x;
        _yBuf[_bufIdx] = y;
        _xSum += x;
        _ySum += y;
        _bufIdx = (_bufIdx + 1) % WINDOW_SIZE;
        if (_bufCount < WINDOW_SIZE) {
            _bufCount++;
        }

        var cx = _xSum / _bufCount;
        var cy = _ySum / _bufCount;

        // 2. Compute 3D acceleration magnitude for floor impact rejection.
        var sqSum = x * x + y * y + z * z;
        var mag   = Math.sqrt(sqSum.toFloat()).toNumber();

        // 3. Detect initial entry into plank orientation.
        if (!_hasMounted) {
            if (x >= X_RELEASE_THRESHOLD) {
                _mountStreak++;
                if (_mountStreak >= _mountStreakReq) {
                    _hasMounted = true;
                }
            } else {
                _mountStreak = 0;
            }
        }

        // 4. Floor impact spike guard (hand-plant at start / push-off at end).
        if (mag >= IMPACT_MAG_THRESHOLD) {
            if (!_hasSettled) {
                // Hand-plant impact while getting into position -> stay in / return to SETTLING.
                _state        = STATE_MOUNT_SETTLING;
                _settleStreak = 0;
                return 0;
            }
        }

        // 5. Plank departure / set termination latch.
        if (_hasMounted && _state != STATE_MOUNT_SETTLING) {
            if (x < X_RELEASE_THRESHOLD || cx < X_RELEASE_THRESHOLD) {
                _releaseStreak++;
            } else {
                _releaseStreak = 0;
            }

            if (_releaseStreak >= _xLatchStreakLen) {
                _isSetLocked = true;
                if (_state == STATE_ARMED) {
                    _state = STATE_READY_TO_ARM;
                }
                return 0;
            }
        }

        // 6. Finite State Machine transitions.
        if (_state == STATE_MOUNT_SETTLING) {
            // Require sustained, quiet straight-arm plank before arming.
            if (_hasMounted && cx >= X_SETTLE_MIN && cy <= Y_SETTLE_MAX && mag < SETTLE_MAG_MAX) {
                _settleStreak++;
                if (_settleStreak >= _settleStreakReq) {
                    _state      = STATE_READY_TO_ARM;
                    _hasSettled = true;
                }
            } else {
                _settleStreak = 0;
            }

        } else if (_state == STATE_READY_TO_ARM) {
            if (cx < X_PLANK_MIN) {
                return 0;
            }

            // Start of push-up descent: forearm tilts so Y_smooth rises above threshold.
            if (cy >= _curRepThreshold) {
                _state           = STATE_ARMED;
                _waveStartSample = curSampleIdx;
                _wavePeakY       = cy;
                _wavePeakIdx     = curSampleIdx;
            }

        } else if (_state == STATE_ARMED) {
            // Track maximum forearm tilt (bottom of push-up).
            if (cy > _wavePeakY) {
                _wavePeakY   = cy;
                _wavePeakIdx = curSampleIdx;
            }

            // If X_smooth collapses below plank minimum during wave, user broke plank (getting up).
            if (cx < X_PLANK_MIN) {
                _state = STATE_READY_TO_ARM;
                return 0;
            }

            // Rep completion: forearm returns to vertical top-of-plank lockout.
            if (cy <= _curResetThreshold && cx >= X_LOCKOUT_MIN) {
                var waveDur = curSampleIdx - _waveStartSample;
                var peakGap = (_lastRepPeakIdx >= 0) ? (_wavePeakIdx - _lastRepPeakIdx) : _debounceMin;

                if (waveDur >= _minWaveDuration && peakGap >= _curDebounce) {
                    _recordConfirmedRep(_wavePeakIdx, _wavePeakY, waveDur);
                    _state = STATE_READY_TO_ARM;
                    return 1;
                }

                _state = STATE_READY_TO_ARM;
            }
        }

        return 0;
    }

    // Updates rep count, cadence debounce, and adaptive fatigue thresholds.
    private function _recordConfirmedRep(peakIdx as Number, peakY as Number, waveDur as Number) as Void {
        if (_repCount > 0 && _lastRepPeakIdx >= 0) {
            var dtPrev = peakIdx - _lastRepPeakIdx;
            var adaptedDebounce = (55 * dtPrev) / 100;
            if (adaptedDebounce > _debounceMax) {
                adaptedDebounce = _debounceMax;
            }
            _curDebounce = (adaptedDebounce > _debounceMin) ? adaptedDebounce : _debounceMin;
        } else {
            _curDebounce = _debounceMin;
        }

        _repCount++;
        _lastRepPeakIdx = peakIdx;

        // Exponential moving average threshold adaptation for deep fatigue sets (from rep 4+).
        if (_repCount >= 4) {
            _peakAvg = (0.30 * peakY.toFloat()) + (0.70 * _peakAvg);

            var adaptedRep = (0.65 * _peakAvg).toNumber();
            if (adaptedRep < 330) { adaptedRep = 330; }
            if (adaptedRep > 420) { adaptedRep = 420; }
            _curRepThreshold = adaptedRep;

            var adaptedReset = (62 * _curRepThreshold) / 100;
            if (adaptedReset < 200) { adaptedReset = 200; }
            if (adaptedReset > 260) { adaptedReset = 260; }
            _curResetThreshold = adaptedReset;
        }

        System.println("PushUpDetector: Rep #" + _repCount + " confirmed (peakY=" + peakY
                       + " dur=" + waveDur + " debounce=" + _curDebounce
                       + " repThresh=" + _curRepThreshold + " resetThresh=" + _curResetThreshold + ")");
    }

    public function getRepCount() as Number {
        return _repCount;
    }

    public function setRepCount(count as Number) as Void {
        _repCount = count;
    }

    public function getSampleCount() as Number {
        return _sampleCount;
    }

    public function getState() as Number {
        return _state;
    }

    public function isSetLocked() as Boolean {
        return _isSetLocked;
    }

    public function getCurRepThreshold() as Number {
        return _curRepThreshold;
    }

    public function getCurResetThreshold() as Number {
        return _curResetThreshold;
    }
}
