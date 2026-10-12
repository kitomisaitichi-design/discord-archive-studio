# Lessons

- When shipping a portable GUI launcher, test that exact launcher on the recipient's occupied default port; a service-only smoke test on another port does not prove the launcher opens the UI.
- When a hidden launcher fails, show the startup error and recovery path; never leave the user with a silent exit.
- When multiple output formats are requested, render them locally from one canonical native cache; never re-fetch Discord once per format.
- When native menus use different system colors, set both option foreground and background and inspect the expanded menu in the actual browser.
