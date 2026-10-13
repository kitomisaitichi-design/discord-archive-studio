# Native archive discovery

- When adding a reader to an existing archive workflow, discover local archives and expose the existing canonical index before offering manual import or upload.
- When saved messages exist outside a filtered ZIP view, read them from the working SQLite index rather than implying the ZIP contains everything downloaded.
- When an existing launcher scans folders, verify that reader discovery uses the same intended roots/depth; launcher discovery alone does not make archives visible.
- When opening a saved conversation, reuse existing search and chronological indexes with bounded paging; do not build a second full message database for the live library.
- When queue movement is expected to feel native, allow dragging the row text/background while excluding interactive controls and keeping active jobs fixed.
