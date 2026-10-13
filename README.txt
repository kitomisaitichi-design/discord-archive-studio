DISCORD ARCHIVE STUDIO 1.3.2 — WINDOWS x64

START
The VBS first checks its own folder and immediate parent. If separated from the
app, it searches the parent tree through six subfolder levels, skipping private
data, runtime folders and junctions. Multiple copies require an explicit choice.
Moving the whole extracted folder keeps the app and Data together; a custom
export destination remains the folder you selected until you change it.

1. Extract the entire Portable ZIP to a normal local folder.
2. Double-click OPEN-DISCORD-ARCHIVE.vbs (or the .bat fallback).
3. The included Python runtime starts a local service and opens an Edge/Chrome
   app window. No Python installation, SDK, npm, mod manager or installer needed.
   It selects an available local port when 8765 is occupied. Settings shows
   the actual address; Data/OPEN-ARCHIVE-UI.url reopens it. A second launch
   reuses the running library. Startup errors show a dialog and a saved report.
4. Open your logged-in Discord desktop client. Its local login can reconnect
   automatically. The first startup also checks an existing saved desktop login.
5. Choose a server, refresh its accessible channels, select channels, and add
   them to the queue. Exports do not send messages or change server settings.

BROWSER CONNECTION — ONE-TIME SETUP
1. Open edge://extensions or chrome://extensions in your regular browser.
2. Enable Developer mode, click Load unpacked, and choose the included
   browser-connector folder. Review the requested Discord and localhost access.
3. In Archive Studio → Settings, generate a pairing code.
4. Click the connector extension, paste that code, and click Pair.
5. Open or reload logged-in Discord. It forwards your existing session locally
   and reconnects on later Discord reloads. Reconnect captured session is a
   manual fallback. The extension must run in the same browser/profile as Discord.
6. Keep the local app running. Set the extension popup port to the actual port
   shown in Archive Studio Settings. Disconnect/switch account revokes pairing.

PACE AND SCHEDULES
Queue: use Settings beside a task, or select tasks and choose Edit selected /
Edit all non-running / Future defaults. Only checked fields change. Running
tasks stay locked; waiting/cooling tasks are editable. Checkpoints and an
already committed batch rest are retained; new rest settings apply afterwards.
Future defaults apply to new manual, People and scheduled tasks. Explicit item
overrides survive repeated enqueueing. Uncheck Use saved future defaults in
Export to use the current form instead for those new additions.
The Export form saves valid settings automatically, per account, including
schedule controls and advanced options. Refresh/relaunch restores them. The
one-off full-history rescan checkbox is deliberately not saved for next launch.

History lists saved conversations and counts, including unfinished batches.
Read messages opens the local transcript. Schedules has search, checkboxes,
Select filtered, Pause/Enable selected, Remove selected, Clear all and Undo.
Removing a server default removes its inherited schedules, preserving explicit
overrides. Removed channels will not be recreated by the server default until
you add them again. Saved messages, current ZIPs and queued exports stay intact.

Export pacing and rescan timing are separate.
- Default: 1,000 scanned messages per batch, a 5-minute cooldown, and at least
  2.5 seconds between API requests. One message reader runs at a time.
- Extra timing variation defaults to 25%: each wait samples additional time,
  so a five-minute rest lasts 5–6.25 minutes. Set 0% for fixed waits or choose
  up to 100%. Discord rate-limit minimums are respected; 429 responses also
  increase request spacing, which gradually recovers after successful reads.
- Choose 100/500/1,000/5,000 messages per batch; cooldowns from 1 minute to 24 hours.
- Scanned counts include existing messages checked for changes, not only new ones.
- Batch usage carries across channels. Each committed page records its cursor.
- Text exports save attachment metadata without downloading media. A batch
  publishes a verified partial current ZIP before resting, then resumes.
- Fixed rescans range from 10 minutes to 7 days. The seven-day button is slow mode.
- Server defaults create independent channel clocks. Explicit channel overrides
  remain separate; disabling a channel override prevents inherited re-enqueueing.
- Adaptive timing uses the count of captured messages in the last seven days to
  aim for about 50 new messages per scan, bounded to 10 minutes–7 days. An empty
  sample starts slow. This is a simple arrival-rate heuristic, not a guarantee.
- Normal rescans request only IDs AFTER the newest saved message ID. They never
  restart old history. An unchanged channel needs only small head checks.
  Optional recent-edit rechecks read at most 500 messages within seven days.
  Full-history rescanning is an explicit one-export action; schedules and
  catch-up tasks cannot inherit it. A scheduled channel without saved data gets
  a current-head baseline, never a silent historical backfill. Use the explicit
  full-history option to archive its older messages later.
- A first manual export of an uncached channel reads its history in paced
  batches. Paused work retains its cursor; partial/imported caches use their
  newest ID for ordinary new-message scans rather than restarting history.
- Due scans coalesce behind current work. Messages arriving after its snapshot
  create one catch-up task; they do not restart the active sweep.
- Running/waiting tasks pause after an app restart. Resume them in Queue.
  Waiting tasks can be moved or removed; cancellation keeps captured messages.
- Close the window to let the service continue quietly. Use Settings → Close
  archive service or CLOSE-ARCHIVE-SERVICE.bat to stop the backend.

ACCESS CHECKS
Every batch checks current server membership, fresh channel permissions and,
when needed, current accessible thread inventory before reading messages.
It never checks existence by blindly requesting a saved channel/thread ID.
User-session thread discovery uses the current DiscordChatExporter-style
per-parent thread-search route; bot-only active-thread routes are not used.
Permission loss or absent resources quarantine affected work and disable its
automatic schedules. 403/404 responses are never retried. Saved data is retained.
Restored access requires an explicit Retry/Resume; schedules must be re-enabled.
There is still a race if access changes after a successful fresh inventory check.

LIBRARY AND IDENTITY
- Queue tray and Queue page show every task in bounded scrollable lists.
  Drag the grip to move any waiting/queued/paused/blocked task; arrow controls
  provide keyboard movement. Active exports stay fixed, including during races.
  The page reserves space for the queue so it cannot cover configuration fields.
- Search server names/IDs in Full and Compact views. The picker filters cached
  names locally and supports arrows, Enter and Escape without a network lookup.
- Preview and Library use a shared continuous transcript border. Preview reads
  50 local messages per page, with Load older saved messages; its attachment
  rows show file metadata even for messages with no text. No remote media loads.
- People on the left menu searches names, usernames and IDs for DM contacts.
  Select individual people, Select filtered, Queue selected, or Queue filtered.
  Friends only uses your actual relationship inventory; friendship is never
  inferred from old messages. Missing DMs stay disabled. Open such a chat normally
  in Discord and refresh contacts; Studio never creates or probes a missing DM.
  Available group DMs are optional and shared chats are queued only once.
- People reuses export formats, filters and gentle batch settings, clears hidden
  person-only/full-rescan flags, and preserves existing job checkpoints. Optional
  adaptive schedules are added only where no channel/server schedule exists.
  Contact metadata is cached by account for ten minutes and refreshed on demand.
  Friend filters and selected contacts persist in this browser for that account.
- Attachments and images download ONLY after you select their checkboxes in
  Library and click Download selected. This queue waits for text jobs to finish.
  Default per-file cap: 10 MB (decimal); adjustable 1–100 MB. Videos always have
  a hard 10 MB cap. Pending selections reserve at most 100 MB / 50 files.
  Unknown sizes are streamed within the cap. Oversized files are skipped and
  keep their metadata/text. No automatic retry of failed media requests.
  Cancel preserves existing downloaded data. Restart pauses pending selections;
  select them again to retry. Only saved, size-eligible files enter ZIP media.
- Indexed search across saved message text, with server/channel/person/date filters.
  A numeric message-ID search also finds that exact saved message.
- Search results load 80 messages per page; old reply targets open from the local
  database. Details includes captured prior versions of a message.
- The Library view hides export-only controls. / focuses its search box.
- Full, Compact and Dock layouts are available. The standalone app window can
  resize into a small dock; ordinary/embedded-browser sessions use the page layout.
- The header theme selector offers Midnight, Light, High Contrast and System.
  Your choice persists in this browser; System follows its light/dark preference.
  Menus, fields, labels and focus outlines use explicit contrasting colors.
- Name changes keep the same Discord user ID. All that ID's messages stay linked.
  Settings supports explicit cross-account aliases and unlinking. Different IDs
  are never automatically merged because their names or avatars look similar.
- Import DiscordChatExporter JSON, modern DCE HTML/TXT, and ZIPs containing JSON.
  Studio ZIP imports restore referenced, hash-verified local media objects.
- JSON is preferred. HTML retains stable message IDs/text with partial metadata.
  TXT without stable IDs is best effort, is kept separate from ID-based channels,
  and currently recognizes US-locale DCE headers with an assumed UTC clock.
  It does not silently guess a locale or merge different people by a display name.
- Byte-identical re-imports are skipped. Richer live data is not replaced by a
  lower-quality old import. Original input files are never renamed/deleted.

EXPORTS AND DRIVE
JSON, HTML, Markdown and plain text can be selected together. Presets persist.
One canonical native message cache feeds every format locally. Selecting four
formats does not fetch the conversation four times. Update ZIP from saved data
regenerates those views without reading Discord.
Filters select exported views; captured native records remain in the database.
Outputs split by message count and optionally an estimated JSON byte size.
Saved reactions, replies, embeds, current edit timestamps and available role
color metadata are retained. Role colors not present in returned data cannot be
invented; the app does not probe departed users' member IDs for color lookups.

The destination gets ONE CURRENT FILE PER SERVER: server_<Discord ID>.zip.
New channel tasks rebuild that same archive. Unchanged export content keeps the
existing ZIP and its modified time. A temporary ZIP is CRC-verified before atomic
replacement; interruption leaves the previous current ZIP intact.
index.html browses its files; channels have stable ID folders; local attachments
use content hashes so identical downloaded bytes are stored only once.

Choose a Google Drive desktop sync folder as destination if desired. Keep the
active app/Data folder local. This app writes the same local ZIP path; actual
cloud sync is performed by Drive and is not verified by Archive Studio. It does
not create timestamped duplicate Drive archives or upload via a cloud account.

COMPATIBILITY AND LIMITS
Windows 10/11 x64 recommended. Browser connector supports Chromium Edge/Chrome.
The app chooses a free port automatically. Only local loopback is used.
Credentials are protected at rest with Windows DPAPI, tied to this Windows user.
The connector keeps session credentials in browser session storage, not sync or
persistent local credential storage. Neither credentials nor pairing keys enter
server ZIPs. Changing accounts pauses work and requires explicit disconnection.

Personal-account automation is unofficial and conflicts with Discord's policy:
https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots
Pacing and access checks reduce needless requests; they cannot guarantee that
Discord will not restrict an account. The specific quoted two-day/two-year
restriction mechanism was not independently established by primary sources.

Previously uncaptured deleted messages or older edit versions cannot be recovered.
Optional edit rechecks cover up to 500 previously seen recent messages within
seven days. A one-time full-history scan can capture older accessible changes.
Archived/private threads appear only through your current accessible inventory;
absent/closed DMs may need to be opened normally in Discord before they appear.
Remote attachment links may expire; select manual downloads for permanence.
Some removed media may no longer be available. Failed downloads are reported,
preserve captured messages, and require an explicit selection to retry. A text
rescan may refresh signed links while the messages remain accessible.
Import requests are limited to 128 MB, with bounded uncompressed ZIP JSON/media.
Very large files should be exported/imported in parts.

BACKUP / UPGRADE / REMOVE
Close the service, then copy Data to a separate local backup. This preserves the
SQLite database, checkpoints, presets, aliases, revisions, media and protected
connection. Data is private. Do not include it in a release shared with others.
To upgrade, extract the new app into another folder, copy the closed Data folder
there, and launch. Keep the old folder until the replacement works. Changes to
existing populated message-table columns create a database recovery copy first.
To roll back, close the service and restore the previous app/Data backup together.
Remove the browser connector from its extensions page and move the closed app
folder to the Recycle Bin. Export ZIPs remain where you chose to save them.

VALIDATION
See VALIDATION.md for actual checks and remaining untested paths. "Bug free" is
a goal, not a guarantee. No messaging feature is included.

ARCHITECTURAL REFERENCES
DiscordChatExporter (Tyrrrz), including the newer supplied .NET 10 package:
https://github.com/Tyrrrz/DiscordChatExporter
Discord Log Parser 1.4.0 (JohnSalchichonGH):
https://github.com/JohnSalchichonGH/discord-log-parser
These were inspected for architecture and input conventions. Their source,
executables, dependencies and user-supplied document instructions are not bundled.
The existing ChatGPT exporter/viewer files were not modified.

ZIP MESSAGE EXPLORER (1.3)
Saved library entries now appear automatically and reuse the working SQLite
search/index directly, including saved messages outside a filtered ZIP view.
Existing message ZIPs are discovered from the destination, app folder and parent
tree through six levels. Inventory is cached for one minute; Refresh list/ZIP
forces discovery. Private data/runtime/recovery folders, junctions, app release
packages and online-only placeholders are skipped. Archives are read in place.
Open outside ZIP remains optional for files outside those roots. No import or
Discord history request is needed for existing indexed messages or local ZIPs.
Choose ZIP reader in the left menu, or Read ZIP in History. Each archive opens
in its own browser tab, with channel selection, calendar activity, hour jumps,
search by words/author, and a continuous timeline. Scroll or use Earlier/Later.
Dates use UTC. Reading indexes saved files locally; it never fetches Discord
history. The timeline renders at most 240 messages, loading 80 at a time.
Use Open ZIP for existing exports (upload limit 128 MB); current server ZIPs
open directly from disk. Reader limits: 10,000 entries, 128 MB per text part,
512 MB total text, 100 MB cached files, 10 MB per included file. Unavailable
or oversized files retain their message metadata. ZIPs remain unchanged.
JSON is preferred. New text/HTML-only exports include native reader metadata;
when JSON is selected it is reused, rather than written twice. Older HTML/TXT
have the metadata their formats preserve. Archived scripts are never executed.
Refresh ZIP loads new saved batches; returning to the tab checks for changes
and offers an update without interrupting the conversation. Reader choices
and your theme are remembered in the browser. Reader indexes and opened ZIPs
live under Data/reader-cache and Data/reader-archives, separate from the working
message database; opening one does not re-import it into your main library.

PROFILE PICTURES
Enable Cache and include profile pictures in Export's advanced settings, or
in the full queue editor, to queue larger saved author selections. Visible pictures
cache automatically as you browse Library and the ZIP reader, including during
committed batch rests. The
ZIP inclusion choice saves with your settings; default is off. Library also offers Queue
profile pictures for its channel/server filters or all saved chats, with
explicit retries. Enable inclusion and Update ZIP from saved data to embed
already cached pictures in existing exports. Text history is not re-fetched.
Pictures use captured user ID plus avatar hash, at 128px WebP; previous captured
hashes remain separate. No extra user-profile endpoint is requested. No avatar
hash means initials. They share the existing 50-file/100 MB pending reservation
cap and each is capped at 1 MB. Deferred authors are reported by the Library
action; queue again when earlier downloads finish. Failures are not retried
automatically. Cached bytes are reused and deduplicated by their SHA-256.
Pictures appear in the reader and saved HTML/JSON; Markdown/TXT retain their
normal text format, with native metadata carrying the author association.
Real CDN availability varies; multi-day operation remains unverified.

QUEUE SELECTION AND MOVEMENT (1.3.1)
Check all selects current editable tasks; Invert selection checks all except
those already selected. Running/physically active tasks remain excluded. Drag
a waiting row by its text or empty area as well as its left handle; buttons,
checkboxes and links keep their normal clicks. Arrow controls remain available.
