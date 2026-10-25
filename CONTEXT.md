# Push-Up Counter - Garmin Connect IQ Project Context

## 1. Project Overview & Objective
A real-time push-up repetition tracking application designed for the **Garmin Forerunner 165 Music (`fr165m`)** smartwatch using Connect IQ SDK 9.x+ (Monkey C).
The app automatically counts push-up repetitions live during a set at 100 Hz, provides audio/haptic feedback, persists metrics locally across app launches, and records structured strength activities to Garmin Connect.

---

## 2. Architecture & UI State

### Views & Navigation
1. **Glance View (`PushUpGlanceView`):**
   - Shows app icon (`glance_icon` 30x30 / `launcher_icon` 54x54).
   - Title: "Push Ups".
   - Subtitles: "X reps today" (Green) and "Y reps this week" (Light Gray).
   - Storage managed in `PushUpStorage.mc` with automatic rollover (Sunday = start of week).
2. **Main / Quick Set View (Page 0 of `PushUpContainerView`):**
   - Page 0 of 3. Designed for quick standalone sets.
   - `START`: Starts live sensor recording session.
   - `STOP`: Opens edit/confirm screen (`PushUpEditView`).
   - Page Indicator: Native-style 3-dot indicator on the **LEFT edge (9 o'clock)** with 3-second auto-hide.
3. **Multi-Set Workout View (Page 1 of `PushUpContainerView`):**
   - Page 1 of 3 (accessible via `DOWN` / scroll).
   - Maintains a single continuous session with multiple sets (laps) and rest timers.
4. **7-Day History View (Page 2 of `PushUpContainerView`):**
   - Bar chart of rolling 7-day push-up history.
5. **Edit / Confirm Dialog (`PushUpEditView` / `PushUpEditDelegate`):**
   - `UP` / `DOWN`: Adjust rep count.
   - `START`: Confirm reps and save workout session.
   - `BACK`: Discard session.

---

## 3. Repetition Detection Engine & Physical Biomechanics

### Biomechanics of a Push-Up on the Wrist
Unlike pull-ups (where gravity pulls along the forearm axis overhead $X \approx -1000\text{ mG}$), a push-up involves:
1. **Top of plank (Resting / In-Position)**:
   - Forearm is nearly vertical with hands on the ground under shoulders.
   - Gravity aligns predominantly along the $+Y$ forearm axis ($Y \approx +800 \dots +1100\text{ mG}$).
   - Movement envelope is quiescent ($\text{envelope} < 70\text{ mG}$).
2. **Bottom of push-up (Chest to Floor)**:
   - As the body lowers, the elbow flexes and the forearm tilts relative to vertical gravity ($Y$ drops toward $+200 \dots +500\text{ mG}$, while $X$ and $Z$ change noticeably).
   - Forearm tilt angle $\theta = \arccos(Y / \text{mag})$ peaks at the bottom of the repetition.
3. **Ascent back to plank**:
   - Pushing back up restores forearm verticality, returning $Y$ to peak gravity ($+800 \dots +1100\text{ mG}$) and tilt angle $\theta$ drops back to a trough.

### 100 Hz Signal Processing Pipeline
- Raw acceleration vector: $(X, Y, Z)$ at 100 Hz.
- Magnitude: $\text{mag} = \sqrt{X^2 + Y^2 + Z^2}\text{ [mG]}$.
- Forearm tilt metric: normalized $Y/\text{mag}$ or angular tilt.
- Running smoothed difference envelope via circular moving average window ($W = 37$ samples / $0.37\text{s}$).

### State Machine Architecture
- `STATE_MOUNT_SETTLING (-1)`:
  - Requires user to establish sustained plank position ($Y \ge +600\text{ mG}$) and hold steady ($\text{envelope} < 70\text{ mG}$) for $\ge 30$ samples ($0.30\text{s}$).
  - Rejects initial shuffling, kneeling, or floor positioning noise.
  - Transitions to `STATE_READY_TO_ARM (0)`.
- `STATE_READY_TO_ARM (0)`:
  - Arms candidate repetition when forearm tilt begins and envelope exceeds threshold $\to$ `STATE_ARMED (1)`.
- `STATE_ARMED (1)`:
  - Reaches inflection point at lowest chest depth (tilt peak).
  - Transitions on falling edge to `STATE_COOLDOWN (2)`.
- `STATE_COOLDOWN (2)`:
  - Confirms repetition upon successful return to plank position (clearing valley / tilt reset) after minimum duration.
  - Enforces minimum debounce ($0.80\text{s} - 0.85\text{s}$) to reject double-bounces.
  - Re-arms for subsequent repetition.
- **Dismount & Release Guard**:
  - If user stands up, lifts hands, or rests ($Y < +400\text{ mG}$ for $\ge 35$ samples), detection latches closed.
  - Rejects spurious counts during post-set recovery or watch operation.

---

## 4. Garmin FIT Recording Architecture (CRITICAL)

### Sport Configuration:
- Create session via:
  ```monkeyc
  ActivityRecording.createSession({
      :name     => "PushUp Quick Set",
      :sport    => Activity.SPORT_TRAINING,
      :subSport => Activity.SUB_SPORT_STRENGTH_TRAINING
  });
  ```
- **Developer Field Contributions** (configured in `resources/fit_contributions.xml`):
  - Field 0 (`total_reps`): `FitContributor.MESG_TYPE_SESSION`, units reps, `nativeNum 7`.
  - Field 1 (`set_reps`): `FitContributor.MESG_TYPE_LAP`, units reps, `nativeNum 25`.

### Critical FIT Lifecycle Rules (Same as Pull-Up)
1. In Quick Set Mode, there is strictly **ONE LAP**. Do **NOT** call `session.addLap()`.
2. Always call `setData(confirmedReps)` on both fields **BEFORE** calling `session.stop()` and `session.save()`.
3. Ensure fields are instantiated immediately upon `createSession()`.

---

## 5. Dataset & Benchmark Performance

- **Active Dataset**: 23 verified `.fit` workout sets recorded live on Garmin Forerunner 165 Music:
  1. `2026-10-17-18-32-46_pushup_10reps_24760030440.fit` (10 reps)
  2. `2026-10-17-18-33-38_pushup_5reps_24760033303.fit` (5 reps)
  3. `2026-10-18-14-15-45_pushup_7reps_24768887775.fit` (7 reps)
  4. `2026-10-18-14-16-09_pushup_3reps_24768888402.fit` (3 reps)
  5. `2026-10-18-14-16-32_pushup_6reps_24768894579.fit` (6 reps)
  6. `2026-10-18-14-22-14_pushup_8reps_24768970087.fit` (8 reps)
  7. `2026-10-18-15-08-27_pushup_15reps_24769590980.fit` (15 reps)
  8. `2026-10-18-17-37-08_pushup_11reps_24771318675.fit` (11 reps)
  9. `2026-10-18-20-31-19_pushup_2reps_24772529760.fit` (2 reps)
  10. `2026-10-19-12-03-26_pushup_20reps_24777798323.fit` (20 reps)
  11. `2026-10-19-16-23-50_pushup_16reps_24780636924.fit` (16 reps)
  12. `2026-10-19-16-32-32_pushup_4reps_24780757001.fit` (4 reps)
  13. `2026-10-19-19-19-55_pushup_5reps_24782884639.fit` (5 reps)
  14. `2026-10-19-19-20-11_pushup_5reps_24782885043.fit` (5 reps)
  15. `2026-10-19-20-14-37_pushup_5reps_24783331305.fit` (5 reps)
  16. `2026-10-19-20-41-28_pushup_3reps_24783520246.fit` (3 reps)
  17. `2026-10-19-20-43-27_pushup_6reps_24783536189.fit` (6 reps)
  18. `2026-10-19-20-43-47_pushup_3reps_24783536508.fit` (3 reps)
  19. `2026-10-20-04-53-07_pushup_10reps_24786270884.fit` (10 reps)
  20. `2026-10-20-15-46-38_pushup_17reps_24792306583.fit` (17 reps)
  21. `2026-10-21-06-19-53_pushup_15reps_24799093989.fit` (15 reps)
  22. `2026-10-21-18-54-18_pushup_20reps_24806704981.fit` (20 reps)
  23. `2026-10-25-09-27-42_pushup_25reps_24843772443.fit` (25 reps)
- **Benchmark Accuracy**:
  - **Exact Match Accuracy**: **23 / 23 (100.0%)**
  - **Parity**: **23 / 23 (100.0%)** between Monkey C `PushUpDetector.mc` and Python `detect_pushups.py`.

---

## 6. Development & Build Commands

- **Build (simulator)**:
  ```powershell
  & "$env:APPDATA\Garmin\ConnectIQ\Sdks\connectiq-sdk-win-9.2.0-2026-06-09-92a1605b2\bin\monkeyc.bat" -d fr165m -f monkey.jungle -o bin/PushUp.prg -y ..\PullUp\developer_key
  ```
- **Export production bundle (.iq)**:
  ```powershell
  & "$env:APPDATA\Garmin\ConnectIQ\Sdks\connectiq-sdk-win-9.2.0-2026-06-09-92a1605b2\bin\monkeyc.bat" -e -f monkey.jungle -o bin/PushUp.iq -y ..\PullUp\developer_key
  ```

### Storage Key Isolation
All storage keys use `pushup_` prefix (e.g., `pushup_date_key`, `pushup_pr_set`) to avoid collision with PullUp app storage keys.

### App IDs & Dual-Release Architecture
To allow testing new features live without resetting your workout history:
- **Production App ID (`90999ee4-98c8-4aa6-98b8-ff9980608e0b`)**: Used for the public release on `main`.
- **Beta App ID (`f4383b90-6800-4603-9dbe-0afa7b5b91df`)**: Used for live device testing on `beta`. Displays a distinct "BETA" badge on launcher icon and titles the app `"Push Ups (Beta)"`.
- Both apps can be installed side-by-side on your watch simultaneously with zero storage collision!

### Build Commands
- **Build Beta (`bin/PushUp-Beta.prg` or `.iq`)**:
  ```powershell
  powershell -File .\build_beta.ps1 -Target prg
  powershell -File .\build_beta.ps1 -Target iq
  ```
- **Build Production (`bin/PushUp.prg` or `.iq`)**:
  ```powershell
  powershell -File .\build_prod.ps1 -Target prg
  powershell -File .\build_prod.ps1 -Target iq
  ```

---

## 7. Code Standards
- Encoding: UTF-8 without BOM.
- Line endings: LF.
- Code language: All comments, logs, and `System.println` statements in English.

---

## 8. Git Repository Integration & Dual-Branch Workflow

- **Isolated Repository**: `PushUp` is configured as an independent Git repository located at `c:\Users\TLP-001\Documents\Garmin\PushUp`.
- **Branch Hierarchy**:
  - `feat/*`: Topic / feature branches for new development or tuning.
  - `beta`: The active staging branch. Features merge here first $\to$ build and test `bin/PushUp-Beta.prg` on watch.
  - `main`: The public production release. Merged from `beta` after live workout verification $\to$ build `bin/PushUp.iq` for store release.
- **Security & Build Exclusions (`.gitignore`)**:
  - **Signing Keys**: `developer_key*`, `*.der`, `*.pem`, `*.key` are strictly ignored and must NEVER be committed.
  - **Binaries & Packages**: `bin/`, `*.prg`, `*.iq`, `*.bin`.
  - **Intermediate Compiler Artifacts**: `mir/`, `internal-mir/`, `gen/`, `*.debug.xml`, `*.mbc`.
  - **Python & Temp**: `__pycache__/`, `scratch/`, `*.log`, `capture_status.txt`.
- **Remote Configuration**:
  - Remote: `origin` pointing to user GitHub repository `https://github.com/yairfink1/PushUp.git`.
  - All pushes use standard Git HTTPS authentication via Windows Credential Manager.
- **Workflow Conventions**:
  - Always verify detector parity and offline test suites before committing code changes.
  - Commit messages must be concise, descriptive, and written in English.

