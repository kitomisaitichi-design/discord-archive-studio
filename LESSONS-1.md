# Lessons

- When an archive contains saved messages, use its newest saved message ID for normal rescans; incomplete historical coverage must not imply a fresh full-history fetch.
- When full-history export is selected explicitly, keep that choice local to the current export; remove it from automatic schedules and catch-up jobs.
- When a schedule discovers an uncached channel, establish its current head as a baseline and require explicit historical backfill.
