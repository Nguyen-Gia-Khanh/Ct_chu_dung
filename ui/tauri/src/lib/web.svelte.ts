import { app, errorText, setStatus } from "./app.svelte";
import { fail, notify } from "./dialogs.svelte";
import { call, onSidecar } from "./rpc";
import type { JobEvent } from "./types";

/** The one running Chrome task: its id, purpose, and the products it finished so far. */
export const web = $state({
  job: null as number | null,
  purpose: "" as "connect" | "update" | "resync" | "",
  progress: "",
  finished: [] as string[],
});

export async function connectChrome(): Promise<void> {
  if (app.webBusy) return;
  await start("web.connect", {}, "Connecting to the debugging Chrome session on port 9222…", "connect");
}

/** Start a browser job; Chrome must have been connected once this session. */
export async function startWebJob(method: string, params: Record<string, unknown>, status: string,
                                  purpose: "update" | "resync" = "update"): Promise<void> {
  if (app.webBusy) return;
  if (!app.chromeConnected) {
    await notify("Save your KiotViet URL in Tab 7, then press Connect Chrome on the tab bar.", "Connect Chrome first");
    return;
  }
  await start(method, params, status, purpose);
}

async function start(method: string, params: Record<string, unknown>, status: string, purpose: typeof web.purpose) {
  try {
    app.webBusy = true;
    web.purpose = purpose;
    web.finished = [];
    web.progress = status;
    setStatus(`${status} You can switch Chrome tabs while it runs.`);
    web.job = await call<number>(method, params);
  } catch (problem) {
    app.webBusy = false;
    web.job = null;
    await fail(errorText(problem), "Chrome task did not start");
  }
}

/** Route job events from the sidecar; call once at startup. */
export function listenToJobs(): void {
  onSidecar<JobEvent>("job", async (event) => {
    if (event.kind === "progress") {
      web.progress = event.text;
      setStatus(event.text);
    } else if (event.kind === "item_done") {
      web.finished = [...web.finished, event.text];
    } else {
      app.webBusy = false;
      web.job = null;
      web.progress = event.kind === "done" ? event.text : "Chrome task needs attention.";
      if (event.kind === "done") {
        if (web.purpose === "connect") app.chromeConnected = true;
        setStatus(event.text);
      } else {
        if (web.purpose === "connect" || event.text.includes("Cannot attach to Chrome")) app.chromeConnected = false;
        setStatus("Chrome task was not verified. Local data is unchanged.");
        await fail(event.text, web.purpose === "connect" ? "Connect Chrome" : "Web update");
      }
    }
  });
}
