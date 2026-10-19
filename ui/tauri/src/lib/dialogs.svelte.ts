import { ask, message, open, save } from "@tauri-apps/plugin-dialog";

/** Native confirmation and notices, so they look like the rest of Windows. */
export const confirm = (text: string, title = "Please confirm") => ask(text, { title, kind: "warning" });
export const notify = (text: string, title = "Warehouse Shelf Mapper") => message(text, { title, kind: "info" });
export const fail = (text: string, title = "Something needs attention") => message(text, { title, kind: "error" });

export async function pickFile(title: string, extensions: string[], label: string): Promise<string | null> {
  const chosen = await open({ title, multiple: false, directory: false, filters: [{ name: label, extensions }] });
  return typeof chosen === "string" ? chosen : null;
}

export async function pickSaveFile(title: string, extensions: string[], label: string): Promise<string | null> {
  return save({ title, filters: [{ name: label, extensions }] });
}

/** In-app modal requests rendered by Modals.svelte (stock entry, number prompt, column choice). */
export interface StockRequest {
  kind: "stock";
  title: string;
  destination: string;
  products: { product_id: string; name: string; stock: number | null }[];
  resolve: (quantities: Record<string, number> | null) => void;
}

export interface NumberRequest {
  kind: "number";
  title: string;
  text: string;
  initial: number;
  resolve: (value: number | null) => void;
}

export interface ColumnsRequest {
  kind: "columns";
  title: string;
  fields: { label: string; optional: boolean }[];
  headers: string[];
  initial: number[];
  resolve: (columns: number[] | null) => void;
}

export interface MergeRequest {
  kind: "merge";
  products: string[];
  resolve: (merge: boolean) => void;
}

export type ModalRequest = StockRequest | NumberRequest | ColumnsRequest | MergeRequest;

export const modal = $state({ current: null as ModalRequest | null });

type Unresolved<R> = R extends ModalRequest ? Omit<R, "resolve"> : never;

function show<T>(request: Unresolved<ModalRequest>): Promise<T> {
  return new Promise<T>((resolve) => {
    modal.current = {
      ...request,
      resolve: (value: T) => {
        modal.current = null;
        resolve(value);
      },
    } as ModalRequest;
  });
}

export const askStock = (request: Omit<StockRequest, "kind" | "resolve">) =>
  show<Record<string, number> | null>({ kind: "stock", ...request });
export const askNumber = (request: Omit<NumberRequest, "kind" | "resolve">) =>
  show<number | null>({ kind: "number", ...request });
export const askColumns = (request: Omit<ColumnsRequest, "kind" | "resolve">) =>
  show<number[] | null>({ kind: "columns", ...request });
export const askMerge = (products: string[]) => show<boolean>({ kind: "merge", products });

export const MAX_STOCK = Number.MAX_SAFE_INTEGER;

export function parseStock(text: string): number | null {
  const trimmed = text.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const value = Number(trimmed);
  return value <= MAX_STOCK ? value : null;
}
