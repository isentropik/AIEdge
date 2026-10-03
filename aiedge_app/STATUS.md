# Navigation and error-state candidate - October 2, 2026

Local dev18 continues the UI/setup phase. It cancels a pending capture review
when leaving for setup, keeps unsaved review and configuration drafts, and
shows a connection failure once on the visible form. Calibration notices remain
on image/alignment/dial steps; status loss clears the MQTT summary. Failed loads
cannot advance setup. Number format reports required values inline and focuses
the affected field without a native browser popup.

Dial names and valid coordinates become drafts while typing, before blur.
Incomplete coordinate typing retains the valid geometry until the field is
finished. Browser route fragments are separate from page-container IDs, and
navigation resets scrolling after rendering without disturbing the same route.

Saved-image browser checks cover 13 routes at 320 px and 1440 px, in light and
dark themes: 52 combinations, with no overflow, visible errors or inherited
scroll position in the final run. Outage, recovery and draft tests are recorded
separately; early failures are retained. Final local UI checks pass 152 tests.
The backend base passes 425 Windows checks with protected real-image replay;
three Linux-only checks are skipped on Windows. Exact candidate package tests
and hashes belong to the validation artifacts. Linux validation for this dev18
candidate remains pending until recorded against its published commit.

Meter type/units remain independent metadata. A unit change never relabels
existing readings: the physical number format must be reviewed and saved in the
new units. Source calibration, separate needle pivot, raw images, number format,
model assets and recognition/accounting implementations remain unchanged.

This is a local app candidate, not a live Home Assistant deployment. Fixture
events use invented timestamps and one protected saved image; they prove no
capture cadence, physical light/exposure behavior, consumption or accuracy.
No labels are saved, and all fixture images and screenshots remain excluded
from training. Scheduled capture, MQTT and archiving remain off.

Physical camera firmware startup/recovery, real light/exposure behavior,
independent recognition accuracy and sustained 30-second operation remain
separate gates. No firmware binary or camera update is included here.
