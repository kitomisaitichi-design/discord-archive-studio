# Reader performance and interaction corrections

- When adding scrollable chat views, buffer bounded local pages and retain existing message elements so media playback and scroll anchors survive new pages.
- When a saved file appears in several chat surfaces, share its local mapping, MIME detection and byte-range serving rather than adding separate eager downloads.
- When queue rearranging needs native feedback, show a floating row and a full-size insertion placeholder, animate neighbors, and preserve running positions.
- When adding event sounds, persist mute in both windows, deduplicate state changes and throttle progress; initialize audio through a user gesture.
- When migrating legacy search metadata, fill bounded local chunks and keep a complete fallback until the index is populated.
- When ZIP media paths contain only hashes, derive MIME types from captured filenames so audio/video remain playable offline.
- When a fixed tray overlaps the queue, calculate drag auto-scroll edges from the visible region above the tray.
- When bounding a transcript, also prune its message and attachment metadata maps so long reading sessions do not retain every visited page.
