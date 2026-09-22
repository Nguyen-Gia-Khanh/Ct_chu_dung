/**
 * Domain types for Warehouse Shelf Mapper UI.
 * Reflects models and database schemas from mapper/common.py and mapper/database.py.
 */

export interface SlotAddress {
  floor: number;
  side: number;
  shelf: string;
  row: number;
  col: number;
}

export interface Shelf {
  id?: number;
  floor: number;
  side: number;
  shelf: string;
  rows_count: number;
  default_cols: number;
  custom_row_cols?: Record<number, number>; // row -> cols mapping if customized
  created_at?: string;
}

export interface CellContent {
  id?: number;
  product_id: string;
  product_name: string;
  barcode: string;
  quantity: number;
  placed_at?: string;
}

export interface ShelfCell {
  row: number;
  col: number;
  loc_id: string;
  items: CellContent[];
  total_quantity: number;
  is_occupied: boolean;
}

export interface Product {
  product_id: string;
  product_name: string;
  barcode: string;
  on_hand: number;
  loc_id: string | null;
  category?: string;
}

export interface OnHandProduct {
  code: string;
  name: string;
  on_hand: number;
  loc_id: string | null;
  selected?: boolean;
}

export interface ReturnedQueueProduct {
  code: string;
  name: string;
  quantity: number;
  loc_id: string | null;
  reason?: string;
}

export interface PrimalQueueItem {
  barcode: string;
  product_name: string;
  quantity: number;
  status: 'pending' | 'assigned' | 'mismatch' | 'ready';
  target_location?: string;
}

export interface CSVData {
  headers: string[];
  rows: Record<string, string>[];
}

export interface CSVColumnMapping {
  code_col: string;
  name_col: string;
  qty_col: string;
  loc_col?: string;
}

export type ActiveTab = 'designer' | 'assignment' | 'primal_queue' | 'browser' | 'cell_transfer' | 'exceptions';

export interface AssignLocationPayload {
  product_id: string;
  product_name: string;
  barcode: string;
  slot: SlotAddress;
  quantity: number;
  upload_to_kiotviet: boolean;
}

export interface TransferCellPayload {
  source_shelf: string;
  source_row: number;
  source_col: number;
  target_shelf: string;
  target_row: number;
  target_col: number;
  action: 'switch' | 'combine';
}

export interface ApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}
