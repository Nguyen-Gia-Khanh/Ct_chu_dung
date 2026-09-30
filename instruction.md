# Desktop UI file map

Start at `ui/desktop/app.py` (`WarehouseMapperApp._build_ui`) to see how the numbered Tkinter tabs are assembled. The view files are:

| Tab | View file | Notes |
| --- | --- | --- |
| 1. Shelf Designer | `ui/desktop/designer.py` | Shelf structure inputs; `ui/desktop/shelf_actions.py` handles saves. |
| 2. Assign Locations | `ui/desktop/location_assignment_view.py` | Queue, compact shelf view, and address controls; `assignment_actions.py` handles moves. |
| 3. Primal Queue / Shelves | `ui/desktop/primal_queue_view.py` | Product search and shelf drawing. |
| 4. Browse Shelves | `ui/desktop/shelf_browser.py` | Uses `ui/desktop/assignment_view.py` to draw saved shelves. |
| 5. Switch / Combine Cells | `ui/desktop/cell_transfer_view.py` | `CellTransferPane._render_shelf` formats the clickable cell addresses. |
| 6. Special Exceptions | `ui/desktop/exceptions_view.py` | Exceptional product placement. |
| 7. Web Location Sync | `ui/desktop/location_comparison_view.py` | Compares and resyncs web locations. |

Shared scrolling behavior is in `ui/desktop/widgets.py`. Shelf address lookup controls are in `ui/desktop/shelf_address_lookup.py`.
