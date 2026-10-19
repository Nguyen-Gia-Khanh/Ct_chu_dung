import type { Changes, WriteResult } from "./types";
import { RpcError } from "./rpc";

export type TabId = "designer" | "assign" | "primal" | "browse" | "transfer" | "exceptions" | "websync";

/**
 * Shared UI state. `changes.seq` increases after every write: the visible tab
 * reloads right away, hidden tabs reload when they are next opened.
 */
export const app = $state({
  tab: "assign" as TabId,
  status: "Ready",
  changes: { seq: 0, last: null as Changes | null },
  scan: { seq: 0, code: "" },
  webBusy: false,
  chromeConnected: false,
  sidecarDown: false,
  designerDirty: false,
});

export function setStatus(text: string): void {
  app.status = text;
}

/** Record a write so every tab showing affected data reloads. */
export function applied<T extends WriteResult>(result: T, status?: string): T {
  app.changes = { seq: app.changes.seq + 1, last: result.changes };
  if (status) app.status = status;
  return result;
}

export function errorText(problem: unknown): string {
  if (problem instanceof RpcError) return problem.message;
  return problem instanceof Error ? problem.message : String(problem);
}

/** True when `tab` is on screen and data changed since it last loaded (`seen` = the seq it loaded at). */
export function stale(tab: TabId, seen: number): boolean {
  return app.tab === tab && app.changes.seq !== seen;
}
