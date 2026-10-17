
## 1.7 discovery continuation — October 2026

The archive reader now links message ZIPs and loose Discord JSON/HTML/Markdown/TXT
exports from the configured destination, app directory and up to seven parent
folders with recursive descendants (bounded at 5,000 folders and 1,000 entries).
Scans skip private Data/runtime, symlinks, junctions and online-only placeholders.
Discovered exports remain in place; their reader indexes are separate from the
canonical chat database. Regression tests cover seven parents, rejection beyond
that boundary, deep subfolder discovery, in-place loose JSON reading, deduplication,
cache/refresh and no source rewrite. The VBS launcher has seven-level parent and
descendant tests. Preserve the populated 1.7 Data and Exports when updating.

# Validation — 2026-10-15

1.7.0: eleven new cases and fourteen affected reader/manual-media cases pass. They cover durable monotone read marks, old-history backfill, frozen unread paging, literal/quoted operators, saved-name autocomplete, native/ZIP searches, manual URL validation, URL/byte deduplication, ZIP asset round trips, private/redirect target rejection, queue caps, text-work deferral, missing files and blocked retry restrictions. An initial test called a nonexistent reader.register helper; using the existing upload API resolved those two fixture errors. Existing direct-image and reader frontend simulations pass; the unrelated full suite was not repeated.

Isolated browser checks cover keyboard author autocomplete, combined channel/image search, unread/empty results, attention search and refresh, and saved images in Library/native reader. The 390-pixel Library check has a 375-pixel page width without horizontal overflow. A retained failed-preview class after offline promotion was found and repaired. Checked pages reported no console errors. Images and failures are synthetic; real Discord/CDN requests and multi-day runs were not exercised. Package, installation and publication evidence is recorded separately in outputs/RELEASE-CHECKS-v1.7.0.json.

1.6.0: focused updater and reverse-cursor checks cover saved defaults, rejected checksums and unsafe/private paths, manifest contents, ETag reuse, public-asset scope, retry timing, active-worker deferral, file rollback, failed-startup restoration and visible rollback receipts. Nine updater/paging cases and thirteen existing reader feature/workflow cases pass. Three frontend simulations cover direct image parsing/escaping/lazy bounds, MIDI/page-cache cancellation and rendering event coalescing. The first selected-test invocation omitted the tests directory needed by existing imports; the corrected invocation passed.

Offline native browser checks confirm persisted update toggle/frequency, successful PNG and animated-GIF URL loads, near-viewport deferral, off/on image controls and an unavailable image fallback with stable reserved dimensions. Both Library and reader reached a 500-message window and paged in reverse without growing that window. Message rows remain keyed, page requests cancel on context changes, and playing-row retention is unchanged. No new frame-time speedup is claimed; this revision caches the container geometry and coalesces Library scroll handling. Private remote media and live Discord capture are not used as tests.

The 390-pixel Settings check exposed pre-existing overflow from navigation and connection buttons. Those rows now wrap at narrow widths; the update controls retain their normal layout.

The updater uses a separate staged runtime to avoid Windows executable locks, waits for the current worker cycle, retains user data and gates the new worker until startup is verified. Automatic installation is limited to portable copies; source checkouts can inspect release metadata. A rollback remains visible and the same failed release is not automatically reinstalled. Verification results for the built portable package, local install cycle, publication and populated recipient are recorded in outputs/RELEASE-CHECKS-v1.6.0.json; they are separate from the earlier release results below. The full unrelated Python suite was not repeated.

1.5.1 is a focused UI correction. The running Export details dialog reproduced 356-719 pixel checkboxes and horizontal overflow. Capture/Files/Pacing now retain the original inputs with 18-pixel checkboxes; desktop and 390-pixel dialog checks show no horizontal overflow. Offline browser checks cover tab/keyboard navigation, Escape/Done, changed settings restored after refresh, History search/empty results and completed-task expansion, named Library filters, 80-message local reading, aligned toolbar/transcript and absence of empty embeds. The existing rendering simulation and affected JavaScript syntax checks pass. No full Python suite or live Discord fetch was repeated for this UI change.

The initial post-refresh preference observation occurred before initialization; the initialized state restored the edited values correctly. A narrow viewport coordinate click selected a different navigation item; keyboard activation reached the intended page and verified the same dialog at 390 pixels. Temporary viewport overrides were reset.

1.5.0: all 136 Python tests pass, plus connector, buffered-reader/MIDI and state-coalescing simulations and syntax checks for every web script. New checks cover generation-cache reuse/invalidation, moved-channel counts, captured name history, explicit alias changes, exact versus surrounding-context jumps, mutable-response isolation and stable reading cursors under incoming messages.

The 128-task, 60-update browser fixture reduced median/p95 synchronous rendering from 20.2/23.5 ms to 1.3/1.8 ms; next-frame latency changed from 36.6/43.4 ms to 6.2/6.6 ms. It retained the active row and focused button in all 60 updates. These are local fixture measurements, not a claim about network speed or every machine. The final harness closes its event stream to exclude an initial SSE connection snapshot from manually supplied progress states.

Actual browser checks covered empty/phrase/combined person-file searches, saved searches and double submission, bookmark persistence, main and reader reading-position restoration, captured person/name history in canonical and ZIP data, escaped tag/code/custom-emoji preservation during highlighting, theme/native-menu readability including corrected Sepia text, settings refresh persistence, system reduced motion overriding Full motion, keyboard pane resize/collapse, mouse/keyboard queue reorder and cancellation, inert ghosts, and main/reader fit at 740px. A 30-second local MIDI fixture remained playing while another page appended, with 160 messages visible and the same player retained. Browser error/warning logs were empty. Private captures were not used for screenshots. Message pages remain bounded; variable-height chat uses style containment rather than speculative offscreen size skipping.

Bookmarks, searches and reading appearance/positions are browser storage for the local app address. Cross-browser/port migration, arbitrary codec coverage, multi-day use and long-running network/account behavior were not tested in this revision. Existing export pacing, media limits, account/access checks and checkpoints were retained. The 99-file portable manifest, ZIP CRC/private exclusions and isolated bundled startup/HTTP/shutdown passed. Recipient maintenance preserves Data/Exports and waits for a committed batch rest. The release check record verifies source and asset hashes separately.

The populated 8768 recipient retained 63,690 messages, all 129 jobs, zero schedules and unchanged committed cursors, boundaries, phases, progress, positions, options and rest. The empty 8767 copy was also updated. Maintenance held only future task starts until the current task completed and released its processing slot; it did not pause the active capture. The temporary hold was removed afterward, preserving any genuine new batch rest. Backups of the prior payload and database remain local under .work/backups.

1.4.1 follow-up: a 10,000-entry metadata fixture reproduces accumulation outside the bounded transcript and now trims to 600 entries while preserving visible message keys. Library file mappings also follow its current 240-message window. The existing buffered-reader, local-media, theme, drag and mute behavior remains unchanged.

1.4.0 checks: all 128 Python tests pass, including combined native/ZIP filters, literal/exact phrases, captured names, stable cursor pagination under incoming messages, local MIME/Range/HEAD/416 behavior and media mappings across search/preview/details. Connector and frontend simulations pass; MIDI timing/sustain/malformed input, bounded page sharing and stale cancellation are covered. Actual offline browser checks use 960 messages and generated PNG, H.264/AAC MP4, MP3, Vorbis OGG, AAC M4A and SMF MIDI fixtures. Audio decoding and click playback, MP3/M4A seeking, MP4 seeking/playback, MIDI playback, and continued playback through page appends were observed; an active video remained as one pinned row after the 240-message window moved. Combined filters returned four matching Robin messages in reader and Library. Five new themes, persisted mute, keyboard queue reorder, refresh persistence and floating mouse-drag placeholder were exercised. Browser error/warning logs were empty. Other codec combinations, full General MIDI instrument fidelity and multi-day playback are not claimed. Mouse edge scrolling advanced without further pointer movement, outside drops and keyboard Escape cancelled correctly, and both narrow main/reader layouts fit at 740 px. The supplied browser control could not send Escape during a held mouse drag, so that specific input combination remains unverified. The 94-file portable manifest, ZIP CRC, private-data exclusions and isolated bundled startup/HTTP/shutdown passed. The populated 8768 copy retained 39,069 saved messages, all 128 jobs, zero schedules and unchanged cursors/options/rest. Its upgraded reader loaded 80 real saved messages with no browser warnings/errors.

Live follow-up: the populated library exposed over 1,000 historical custom IDs. Visible-reference priority now promotes the current reading material ahead of background IDs while preserving the shared pending cap; a regression verifies the queue stays at 50. This avoids making a current reader wait for a whole historical emoji backlog.

1.3.3 checks: 123 Python regressions cover global ID reuse across names/servers/reactions, static/animated CDN selection, code literals and escaping, shared reservations, durable deferred references, explicit failed retries, rest priority, grouped ZIP publication, offline embedded assets and source-bound HTTP requests. Actual isolated UI checks cover readable pending labels, inline graphics, shared-cache reuse, emoji-library filtering, empty search, scrolling and double refresh. Two captured IDs used two simulated downloads total. Synthetic CDN data is not a live availability guarantee.

The populated 8768 recipient was updated during a committed rest: 27,069 messages, all 128 tasks, zero existing schedules and unchanged settings/checkpoints/rest were retained. Its reader loaded four real CDN profile pictures in place without an update banner. This is a current live smoke check, not exhaustive CDN or multi-day validation.

1.3.2 correction: 113 Python tests, connector simulation and all web JavaScript syntax checks pass. New regressions cover saved-ID resolution and input bounds over HTTP, canonical and ZIP author sources, duplicate requests, failed retry suppression, shared caps, rest-window priority and unchanged message generations, plus local ZIP invalidation after a cached picture arrives. Actual isolated browser checks used 1,000 saved messages and synthetic PNG responses: browsing queued three captured versions once, identical bytes occupied one SHA-256 object, images appeared without an update banner, scrolling did not reset, ZIP and Library reused the same cache, empty search and double refresh worked, and the Library bulk picture button returned three already cached authors. Real CDN availability and multi-day operation remain separate live checks.

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

1.3 reader validation: regression tests cover native metadata for text-only ZIPs,
JSON reuse, format fallback, per-archive isolation, repeat-open deduplication,
date/hour indexing, FTS search, bounded bidirectional paging, changed-ZIP cache
invalidation, Windows replacement, unsafe original/normalized paths, empty
channels, avatar hash changes, deduplicated bytes, raster-only assets, offline
profile rendering, opt-in defaults, caps, and text priority. HTTP checks cover
reader-tab session establishment, local routes and invalid asset identifiers.
The UI fixture contains synthetic messages and a generated test raster; it
does not run a Discord connection or export worker. Real CDN downloads, live
extension capture and multi-day queue operation remain unverified.

All 103 Python tests pass, along with connector simulation and all UI script
syntax checks. Actual isolated browser checks covered calendar/day selection,
hour jumps, empty search/channel, 80-message paging with a 240-node ceiling,
scroll-to-load, saved search/day/channel after refresh, readable light/midnight
themes, profile-setting persistence, the main ZIP catalogue, file-chooser ZIP
opening and repeat opening, and corrected double-refresh behavior. Reader and
main-app browser error logs were empty at the inspected checkpoints. Proof:
`outputs/zip-reader-1.3.0-proof.jpg` (synthetic conversations, not user data).

1.3.1 correction: all 107 Python tests pass. New checks cover canonical-index reading without ZIP/import/network/index-build calls, calendar/hour/FTS/author/reply/bidirectional cursors, filtered ZIP versus full saved-library counts, automatic unrecorded ZIP discovery, depth-six/seven boundaries, cached/forced scans, path deduplication, destination changes and relocated folders. Actual isolated UI verified native library reading, day/hour jumps, Check all (seven editable tasks, running excluded), invert-all and invert-one, dragging from row text with durable order after refresh, fixed running row and Settings control clicks. Browser error logs were empty at the inspected checkpoints. A read-only check of the user's 24,069-message index returned an 80-message page in 87.88 ms and overview in 12.90 ms on this machine; these are a single measured local sample, not a large-history performance guarantee. No live queue was modified as a test.

