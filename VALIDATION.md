# Validation — 2026-10-12

## Verified

- Runtime settings checks cover waiting-task edits, selected/all/future targets,
  transactional claim/edit races with the actual worker loop, rollback on
  stale/running/cross-account selection, untouched options/checkpoints/rest,
  future manual/DM/scheduled additions, explicit overrides, per-account
  preferences, restart persistence and stale-save timestamp protection.
- Actual isolated UI checked cooling-down edits, bulk changes while running
  work stayed locked, empty/double submission, future-only updates, and form
  restoration after refresh and a service restart on a different browser origin.
- Native cscript discovery checks verify whole-folder relocation, depth six
  success/depth seven rejection and explicit ambiguity handling. No live
  recipient library was moved as a test.
- Schedule management checks cover owner-scoped transactional bulk actions,
  server/inherited propagation, independent overrides, deletion exclusions,
  repeat removal and undo without overwriting newer edits or changing jobs.
  Actual isolated UI exercised search, selection, pause/removal/undo, invalid
  and double-save edits, persisted refresh, clear cancellation and clear/undo.
  The in-page confirmation works in IAB; its browser console showed no errors.
- Live History displays completed and partial saved counts and opens the
  corresponding local transcript. All 45 existing schedules expose Edit and
  pause/enable controls; no live schedules were changed for verification.
- People tests cover account-scoped cache, renamed contacts, real friend-type
  filtering, denied friends metadata, unavailable DMs, shared-chat/repeat dedup,
  preserved schedule overrides and private forward-sweep options on re-enqueue.
- Reordering tests preserve active positions, cursor/boundary/progress/options,
  durable cooldown and restart order; stale/running drops are rejected. Preview
  uses local keyset pages with no gaps when new messages arrive.
- Actual synthetic UI checked 16 reachable queued tasks, scrolling to the end,
  keyboard arrows, pointer drag with a saved order, server-name search/no results,
  and People search/friends selection. A fixed queue overlay covering advanced
  settings was reproduced and fixed with measured page spacing; the previously
  blocked controls were then exercised live.
- The populated recipient library was updated during its batch rest. Its 13
  tasks and saved message checkpoints were retained; capture continued beyond
  6,000 messages. Live contact metadata validated 140 contacts and 63 friends,
  without initiating a bulk DM export as a test.
- 92 Python unittest checks pass: canonical ID/hash deduplication, edit history,
  FTS search, import quality/rollback, aliases, scheduling, queue restart/catch-up,
  access gating, 403/404 no retry, 429 pacing, HTTP authorization, DPAPI/AES-GCM,
  independent channel export views, atomic ZIPs, and manual attachment bounds.
- Launcher regressions cover occupied ports, exclusive Studio port binding,
  one process per library, and matching the saved port to the library identity.
  The actual VBS launcher now opens the existing recipient library in Edge on
  port 8767 while the unrelated service occupying 8765 remains untouched.
  Restart prefers the saved library port, preserving the browser origin when
  that port remains free. The connector checks app identity before sending credentials.
- Actual Edge checks exercised Midnight, Light, High Contrast and System;
  theme selection survives refresh and the empty Library works. Select options
  resolve to explicit matching background/foreground colors in each palette.
  Browser screenshots omit the operating-system native popup itself; its style
  values and expanded accessibility state were checked, not its captured pixels.
- Positive stochastic waits stay within the selected baseline plus variation;
  fixed mode and Discord reset minimums are verified. All four export formats
  publish from local records with Discord.get forbidden by the test.
- Incremental tests verify a three-year cached checkpoint only requests its
  350 newer messages using `after`, continues from each saved forward cursor,
  and requests no page on an unchanged repeat. Partial/imported caches never
  implicitly restart historical export. Scheduled fresh channels establish a
  head baseline; full-history actions are removed from schedules and catch-ups.
  Recent-edit rechecks are opt-in and bounded to 500 messages / seven days.
- A live forward `after=<saved checkpoint>` request with limit 1 passed after
  fresh normal-channel access preflight and returned zero new records. No
  credentials, private IDs or message contents were printed or packaged.
- The simulated browser-connector event check passes: localhost-only forwarding,
  session-only credential storage, duplicate suppression and reload reconnection.
  UI and connector JavaScript syntax checks pass.
- Manual media checks prove no downloads during text export, text priority,
  pending budget enforcement, known/unknown size limits, no automatic retry of
  oversized files, partial cleanup, restart pause, cached oversized video
  exclusion, hash-addressed media and ZIP import round-trip.
- Actual native desktop login was validated with `/users/@me` and a protected
  local vault. Corrected normal-channel access preflight, one real message read,
  and a small server ZIP CRC check passed. Private samples stayed under `.work`.
- Actual in-app-browser checks exercised Full/Compact/Dock, seven-day mode,
  empty and populated search, refresh, empty preset validation, double preset
  submission, pause/reorder and applying settings to queued jobs.
  A Library initial-load bug was reproduced, fixed and refresh re-tested.
- A real two-port UI check exposed cookie collision between local instances.
  Cookies now include the app port. A shared-browser-cookie regression test
  verifies both instances remain authorized after opening the other.
- A synthetic attachment import was exercised through the real file chooser.
  Selecting a 6 MB image with a 5 MB cap produced a visible skipped result;
  an 11 MB video was unselectable. Message details retained both metadata and
  text. No remote image fetch is initiated merely by viewing uncached messages.
- Earlier synthetic 100,000-message measurement: insertion 5.32 s, rare search
  14.37 ms, common search 231.73 ms, empty paged search 174.93 ms. Hardware and
  query dependent; these are measured local values, not universal guarantees.

## Corrections and boundaries

A bot-style guild-wide active-thread route returned 403 during the initial live
metadata check. The app stopped, did not retry it and did not read messages
after that failure. The code now uses per-parent user-session thread search,
matching the current DiscordChatExporter source. Ordinary-channel validation
skips thread discovery. Simulated thread-route tests pass; live thread search
has not been verified.

The actual unpacked browser extension has not been installed or live tested.
Complete one-time loading/pairing as described in README.txt. Native standalone
window resizing and the Windows folder picker have not been exercised through
their real UI. Long multi-day runs, permission changes during live paging,
actual CDN downloads, and Google Drive cloud synchronization remain untested.

The specific quoted two-day / two-year Discord restriction mechanism has not
been independently established. No claim of enforcement immunity or bug-free
behavior is made. Deleted/unseen content is not recoverable.

## Package checks

The portable runtime launched from the release folder with an empty working
library and automatic connection disabled for this smoke test. Bundled SSL,
SQLite FTS5, ctypes and DPAPI checks passed. Release manifests are checked against
their file sizes and SHA-256 hashes. Both Portable and Source ZIPs passed CRC;
credentials, databases, private samples, development backups and caches were
excluded. The clean release UI opened, empty Library refresh passed, and its
browser console had no errors. These checks do not imply live extension capture
or a real TLS handshake was tested in the packaged process.
