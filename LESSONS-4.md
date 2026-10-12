# Lessons

- When runtime settings are requested for one, selected, all or future tasks, expose those targets explicitly and preserve checkpoints under a transaction that also excludes newly running jobs.
- When Pause changes the displayed status before a request finishes, retain a worker-owned processing lock until its finally block exits; status alone does not establish that settings are safe to edit.
- When the user asks not to redo settings at launch, persist the actual Export form as well as future-job defaults, keep them account-scoped, and verify refresh and process restart.
- When full runtime editors accept numeric values beyond a compact selector’s presets, add a visible custom option before restoring it; assigning an absent option silently clears the value.
