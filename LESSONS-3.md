# Lessons

- When confirming portable launcher discovery, distinguish relative whole-folder launching from recursive fallback; verify the requested depth and refuse to silently select among multiple libraries.
- When destructive controls must work in the in-app browser, use an accessible in-page confirmation dialog; native confirm can block the browser-control surface.
- When exposing a management page, provide selection and bulk actions with recoverable removal; deleting a channel schedule must also stop its server default from recreating it.
- When the user asks to see exported work and manage schedules, show partial saved channel counts as well as completed jobs, and expose schedule actions directly in navigation.
- When constructing multi-hunk native patches, first remove redundant anchors and verify ascending source line order within each file; a trailing earlier header fails the entire patch.
- When the user needs to scroll every queued task, remove render limits as well as adding overflow; hidden tasks cannot be reached by a scrollbar.
- When the user asks for natural conversation reading, render one continuous transcript with shared boundaries instead of independent message cards.
- When adding People bulk exports, resolve currently available DM channels by stable recipient IDs and reuse the canonical queue, checkpoints and schedules.
- When exposing friends-only selection, use a separate friends inventory and show unavailable data explicitly; never infer friendship from old messages.
- When recipient metadata repeats across one-to-one and group DMs, preserve the current one-to-one name and replace it only with a freshly fetched friends record.
- When a repeated enqueue updates a resumed queued job, preserve its private sweep options alongside its cursor; losing the forward direction can accidentally traverse older history.
- When a fixed queue tray overlaps form controls, reserve its measured height in the page layout; expand advanced settings only after the header is reachable.
