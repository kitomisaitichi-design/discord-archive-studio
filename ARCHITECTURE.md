# Discord Archive Studio

`studio/credentials.py` uses Windows DPAPI and CNG AES-GCM for the current user's desktop profiles. `Connection` serializes account acceptance, pins an account ID, and protects a newly refreshed session against an old request's authentication failure. Disk changes trigger a bounded scan; unchanged credentials do not trigger new account requests.

`studio/access.py` checks current membership and computes channel permission overwrites from current roles/member data. It lists user-accessible threads through search on an already accessible parent. Ordinary channel jobs skip thread discovery. It never calls an individual saved resource to test whether it still exists. Missing/denied resources quarantine work; permission changes after preflight remain a race.

`studio/store.py` stores one canonical row per message ID, higher-quality source priority, prior captured revisions, attachment object hashes, author snapshots, explicit person aliases, queue checkpoints, independent schedules and publication state. SQLite WAL provides transactional pages and an FTS5 text index. Message body text and native IDs are preserved. File hashes identify byte-identical imports; TXT identities are synthetic and separate.

`studio/runtime.py` runs one export worker. A frozen newest-ID boundary separates current history from arrivals during the run. Committed cursors survive restarts and cooldowns. Request pacing is shared with metadata readers. A global message budget counts across channels; due jobs coalesce without interrupting a sweep. Adaptive intervals are independently derived from each channel's saved seven-day sample.

Normal incremental jobs page forward with `after=<newest saved ID>`, including imported or partially exported history. No-change heads produce no message-page request. Recent-edit scans are opt-in and bounded; full-history scans require an explicit current-job option and never propagate into schedules/catch-ups. An uncached scheduled channel establishes a current-head baseline. Initial manual history exports page backward, and paused tasks preserve their original direction and cursor.

`studio/exporting.py` downloads only manually selected Discord attachments, without session authorization. A separate persistent media queue runs after text work, reserves at most 100 MB / 50 files, and caps video bytes at 10 MB. Content-Length and bounded streaming enforce unknown-size limits. Text paging never invokes media downloads. Downloaded bytes become shared hash objects; server ZIPs retain independent channel views, include only eligible saved objects, validate CRC, and replace atomically. Presentation options and channel generations identify no-op publications. A richer live record takes priority over a lossy old import.

`studio/importing.py` parses JSON, streams DCE HTML markup without running it, and keeps ID-less TXT separate. Studio ZIP media objects are restored only by their validated content hashes. Arbitrary ZIP paths are never extracted.

`studio/server.py` binds only to loopback, validates Host/Origin, protects UI APIs with a SameSite/HttpOnly session cookie, and separately scopes a paired browser connector. Server-sent events deliver state changes without busy frontend polling. Logs omit request paths/search text and credentials. `web/` uses vanilla JS/CSS and bounded result pages. `studio/window.py` operates only on a uniquely named standalone browser app window; embedded browser sessions keep layout controls local.

The portable runtime consists of CPython, its standard library and required native modules. There are no pip/npm runtime dependencies. Development-only unit tests, synthetic fixtures, benchmarks, backups, reference files and all private Data are excluded from the Portable ZIP.
