// Shapes returned by mapper/rpc/api.py.

export interface Changes {
  products: string[];
  slots: string[];
  shelves: boolean;
  catalog: boolean;
}

export interface ProductRow {
  product_id: string;
  name: string;
  brand: string;
  hot: boolean;
  location: string;
  stock: number | null;
  on_hand: boolean;
}

export interface SearchResult {
  rows: ProductRow[];
  total: number;
  size: number;
  ready: number | null;
}

export interface Shelf {
  shelf_id: number;
  floor: string;
  side: string;
  code: string;
  label: string;
}

export interface GridCell {
  row: number;
  cell: number;
  slot_name: string;
  count: number;
}

export interface GridModel {
  floor: string;
  side: string;
  code: string;
  layout: number[];
  rows: GridCell[][];
}

export interface ContentRow {
  product_id: string;
  name: string;
  slot: string;
  stock: number | null;
  assigned_at: string;
  modified_at: string;
}

export interface ShelfView extends GridModel {
  shelf_id: number;
  label: string;
  contents: ContentRow[];
}

export interface SlotAddress {
  slot_id: number;
  shelf_id: number;
  floor: string;
  side: string;
  shelf_code: string;
  row_number: number;
  slot_number: number;
  slot_name: string;
}

export interface OnHandRow {
  product_id: string;
  name: string;
  stock: number | null;
  queued_at: string;
}

export interface StagedRow {
  product_id: string;
  product_name: string;
  staged_locations: string;
  locations: string | null;
  csv_updated: number;
  catalog_updated: number;
  created_at: string;
}

export interface Difference {
  product_id: string;
  /** The same ID in KiotViet's 5-3-rest spelling, e.g. 06451-961-405. */
  web_code: string;
  wrong_location: string;
  true_location: string;
  can_resync: boolean;
}

export interface JobEvent {
  job: number;
  kind: "progress" | "item_done" | "done" | "error";
  text: string;
}

export interface WriteResult {
  changes: Changes;
  count?: number;
}

export interface Column<R> {
  key: string;
  label: string;
  width?: string;
  align?: "left" | "right";
  value: (row: R) => string | number | null | undefined;
}
