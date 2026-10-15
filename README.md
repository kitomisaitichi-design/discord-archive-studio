# Discord Archive Studio

A portable Windows client for keeping a searchable local Discord archive. It reads conversations, saves each message once, and updates one current ZIP per server.

## Download and run

Download the **Portable ZIP** from [Releases](https://github.com/kitomisaitichi-design/discord-archive-studio/releases/latest), extract it completely, and double-click **OPEN-DISCORD-ARCHIVE.vbs**. The bundled runtime opens the app in an Edge or Chrome window; no Python installation is required. The `.bat` launcher is a visible fallback.

## What it does

- Silent application updates are enabled by default in portable copies. Settings controls the check frequency (daily by default) and off toggle. Public release downloads are checked against GitHub's SHA-256 digest and the package manifest, staged locally, and installed after the worker finishes its current work. Startup failure restores the previous files; Data and Exports stay in place.
- Direct JPG, PNG and GIF links display near the viewport, with four concurrent image loads, reserved image space, a failure link and a saved Reading & appearance toggle. These links need a reachable image host; attachment downloads remain manual. The Library, reader and preview keep a rolling window of up to 500 saved messages with bounded adjacent-page prefetch.
- Export details use readable Capture, Files and Pacing tabs. History groups searchable conversations by server or DMs and keeps completed task details expandable. Library aligns its search controls and transcript, resolves filter names and keeps message actions accessible on hover or keyboard focus.
- Retained task rows, coalesced progress events, deferred hidden-page rendering and bounded local metadata caches keep updates responsive.
- Ctrl+K search/navigation, named saved searches, removable filter chips, safe text highlighting, bookmarks, last-read restoration and jumps into surrounding saved conversation.
- Captured-person drawers show saved name history and explicit identity links without enumerating server members.
- Saved motion, spacing and text-size controls; resizable/collapsible panes and contextual export/download panels keep the reading area clear.
- Incremental ID-based scans resume from saved cursors. Ordinary updates fetch only newer messages; full historical rescans require an explicit choice.
- One serialized export queue with adjustable batches, durable pauses, positive random timing variation and rate-limit waits.
- Full runtime settings for one task, selected tasks, all non-running tasks, or future additions. Cooling-down work is editable; active work is locked, and checked-field changes preserve other settings and checkpoints.
- Export form preferences and future queue defaults are saved per account and restored after refresh or relaunch.
- Independent per-channel schedules from ten minutes to seven days, including local seven-day activity-based timing.
- Fresh membership and accessible-resource checks before message batches. Access loss stops affected work and preserves saved data.
- A canonical native message cache generates JSON, HTML, Markdown and plain text locally. Selecting several formats does not fetch each conversation repeatedly.
- SQLite full-text search, paged offline message browsing, prior captured edits and explicit reversible identity links.
- Manual attachment downloads run after text jobs, with bounded file and queue sizes. Videos above 10 MB are excluded.
- Midnight, Light, High Contrast and System themes, plus Full, Compact and Dock layouts.
- Scrollable queues with drag grips and keyboard arrows, searchable server names, and a continuous reading pane.
- A People directory for selecting DM contacts or friends, bulk queueing available chats, and adding independent adaptive schedules.
- History shows saved conversation counts, including partial batches, with direct reading links. Schedules supports search, selection, bulk pause/enable/removal, clear all and undo.
- The native VBS launcher supports folder moves and bounded fallback discovery through six subfolder levels, with an explicit choice among multiple copies.
- One current ZIP per server, verified before atomic replacement. Unchanged content retains the existing file and timestamp.

Desktop reconnect uses the existing local session. Browser reconnect requires one-time installation and pairing of the included connector; its port must match the address shown in app Settings.

See [README.txt](README.txt) for setup, scheduling, import formats, backup and upgrade instructions; [ARCHITECTURE.md](ARCHITECTURE.md) for implementation; and [VALIDATION.md](VALIDATION.md) for checks and limitations.

## Development

Standard-library Python 3.12 backend and vanilla JavaScript frontend. Run `python app.py --demo --no-connect` for a synthetic local demo, or `python app.py --no-connect` for an empty library. Run `python -m unittest discover -s tests -v` and `node tests/test_connector.cjs` for verification.

Build the portable Windows package with `python tools/build_release.py --python-runtime <Python-3.12-runtime-folder>`. The builder excludes credentials, databases, development data and logs. Keep the working `Data` folder private.

## Limits

Personal-session automation is unofficial and conflicts with [Discord's self-bot policy](https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots). Pacing and preflight do not guarantee account safety. Previously uncaptured deletions and old edit versions cannot be recovered. Live extension capture, real CDN downloads and multi-day runs remain unverified; see the validation record.

No message composer is included. Google Drive synchronization is performed by the user's desktop Drive client.

## References

[DiscordChatExporter](https://github.com/Tyrrrz/DiscordChatExporter) and [Discord Log Parser](https://github.com/JohnSalchichonGH/discord-log-parser) informed paging and import conventions. Their executables and source are not bundled. Bundled runtime notices are in [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt).
