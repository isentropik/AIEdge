# Development time

AIEdge is being **vibe coded with Codex**, with user direction, image labeling and hardware testing. Approximately **36 hours** of recorded project activity so far, as of September 23, 2026 (Pacific time).

This is an evolving estimate of work on this fork and its meter-training work, not the time spent creating the upstream project. AIEdge builds on [AI-on-the-edge-device](https://github.com/jomjol/AI-on-the-edge-device) by jomjol and its contributors; their work remains credited separately.

The total is reconstructed from two project chats, rounded to the nearest hour. Overlapping chat activity counts once. Gaps longer than five minutes are excluded, so long builds can be undercounted and short waits can be included. This is neither human labor hours nor model compute time.

## Updating the total

Run `tools/project-time/update.py` with the relevant local transcript paths (`--session`, repeatable), the meter-work starting timestamp (`--after`), and `--report docs/project-time.json`. Update the rounded number here at development milestones. Add other project chats when identified; do not include unrelated Home Assistant work. The initial cutoff is `2026-09-15T04:50:52.773Z`.

Only aggregate timing information is published in [the time report](project-time.json). Conversation text, credentials and local transcript paths stay private. Recompute from source records rather than adding totals together, to avoid counting the same work twice.
