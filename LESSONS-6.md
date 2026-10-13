# Lessons

- When manual attachment rules are requested, keep automatic visible profile-picture caching separate from attachment downloads.
- When text exports rest between committed batches, let bounded profile-picture work use those rests rather than waiting for the entire queue to finish.
- When reading saved chats, hydrate images in place from captured author metadata and preserve the transcript position.
