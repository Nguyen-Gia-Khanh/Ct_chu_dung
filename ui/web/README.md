# Deprecated web UI

This React/TypeScript interface is retained for reference. The supported app is
the Tkinter UI in `ui/desktop/`, launched from the project root with
`python warehouse_mapper.py`.

The source, build script, and checked-in offline bundle live in this folder.
The local API remains in `mapper/api/`. No web UI rebuild or optimization is
planned as part of the desktop refactor.

For historical development, run `npm install` and `npm run dev` from this
directory. The Vite server proxies `/api` to the Python server on port 8000;
start that server with `python -m mapper --ui web`. Node.js is required to
rebuild the TypeScript source.
