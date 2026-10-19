"""JSON-over-stdio service that lets the Tauri desktop app use mapper/.

Run with ``python -m mapper.rpc --db PATH``. Each stdin line is a request
``{"id", "method", "params"}``; each stdout line is a reply ``{"id", "result"}`` or
``{"id", "error": {"type", "message"}}``, or an event ``{"event", "data"}``.
"""
