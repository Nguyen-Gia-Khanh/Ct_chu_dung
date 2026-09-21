/**
 * Coordinate and string normalization utilities for Warehouse Shelf Mapper.
 * Ported from mapper/common.py and utils/barcode_scanner.py.
 */

import { SlotAddress } from '../types';

/**
 * Case- and accent-insensitive search, handling Vietnamese diacritics.
 */
export function normalizeSearch(value: string): string {
  if (!value) return '';
  return value
    .replace(/đ/g, 'd')
    .replace(/Đ/g, 'D')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase();
}

/**
 * Clean and uppercase a location segment (e.g. floor, shelf, side).
 */
export function cleanLocationSegment(value: string): string {
  if (!value) return '';
  const normalized = normalizeSearch(value).trim().toUpperCase();
  const hyphenated = normalized.replace(/\s+/g, '-');
  return hyphenated.replace(/[^A-Z0-9_-]/g, '');
}

/**
 * Format slot coordinates to standard Location ID:
 * Example: floor 1, side 1, shelf A, row 8, col 10 -> "L1-1A8-10"
 */
export function makeSlotName(
  floor: string | number,
  shelfCode: string,
  rowNumber: number,
  slotNumber: number,
  side: string | number = '1'
): string {
  let floorCode = cleanLocationSegment(String(floor));
  if (!/^L[0-9]+$/i.test(floorCode)) {
    floorCode = `L${floorCode}`;
  }
  return `${floorCode}-${cleanLocationSegment(String(side))}${cleanLocationSegment(shelfCode)}${rowNumber}-${slotNumber}`;
}

/**
 * Extract shelf base code (e.g. "L1-1A" from floor 1, side 1, shelf A).
 */
export function getShelfCode(
  floor: string | number,
  side: string | number,
  shelf: string
): string {
  let floorCode = cleanLocationSegment(String(floor));
  if (!/^L[0-9]+$/i.test(floorCode)) {
    floorCode = `L${floorCode}`;
  }
  return `${floorCode}-${cleanLocationSegment(String(side))}${cleanLocationSegment(shelf)}`;
}

/**
 * Parse a standard location string (e.g. "L1-1A8-10") into a SlotAddress.
 */
export function parseSlotName(locId: string): SlotAddress | null {
  if (!locId) return null;
  const match = locId.trim().match(/^L(\d+)-(\d+)([A-Za-z]+)(\d+)-(\d+)$/i);
  if (!match) return null;

  return {
    floor: parseInt(match[1], 10),
    side: parseInt(match[2], 10),
    shelf: match[3].toUpperCase(),
    row: parseInt(match[4], 10),
    col: parseInt(match[5], 10),
  };
}

/**
 * Convert an 11-character scanner value to the stored 5-3-3 ID format.
 * Example: "06410KFL850" -> "06410-KFL-850"
 */
export function formatProductId(value: string): string {
  if (!value) return '';
  const compact = value.trim().replace(/-/g, '');
  if (compact.length === 11 && /^[a-zA-Z0-9]+$/.test(compact)) {
    return `${compact.slice(0, 5)}-${compact.slice(5, 8)}-${compact.slice(8)}`;
  }
  return value.trim();
}
