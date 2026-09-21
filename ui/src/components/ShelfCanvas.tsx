import React from 'react';
import { ShelfCell } from '../types';
import { makeSlotName } from '../utils/coordinates';

interface ShelfCanvasProps {
  floor: number | string;
  side: number | string;
  shelf: string;
  rowsCount: number;
  colsCount?: number;
  rowColsMap?: Record<number, number>;
  cellsData?: Record<string, ShelfCell>;
  selectedRow?: number | null;
  selectedCol?: number | null;
  onCellClick?: (row: number, col: number, locId: string) => void;
  title?: string;
  readOnly?: boolean;
}

export const ShelfCanvas: React.FC<ShelfCanvasProps> = ({
  floor,
  side,
  shelf,
  rowsCount,
  colsCount = 10,
  rowColsMap = {},
  cellsData = {},
  selectedRow = null,
  selectedCol = null,
  onCellClick,
  title,
}) => {
  // Generate rows array [1, 2, ..., rowsCount]
  // In app.css: .shelf-canvas-grid has `flex-direction: column-reverse`, so Row 1 renders at the bottom!
  const rows = Array.from({ length: rowsCount }, (_, i) => i + 1);

  // Compute total cells and occupied cells
  let totalCells = 0;
  let occupiedCount = 0;

  rows.forEach((r) => {
    const cols = rowColsMap[r] || colsCount;
    totalCells += cols;
    for (let c = 1; c <= cols; c++) {
      const locId = makeSlotName(floor, shelf, r, c, side);
      if (cellsData[locId]?.is_occupied) {
        occupiedCount++;
      }
    }
  });

  return (
    <div className="shelf-canvas-container">
      <div className="shelf-canvas-header">
        <div>
          <strong>{title || `Shelf: L${floor}-${side}${shelf}`}</strong>
          <span style={{ marginLeft: '0.75rem', color: 'var(--text-muted)' }}>
            ({rowsCount} rows × ~{colsCount} cols)
          </span>
        </div>
        <div style={{ display: 'flex', gap: '1rem' }}>
          <span>
            Occupied: <strong style={{ color: '#2e7d32' }}>{occupiedCount}</strong> / {totalCells}
          </span>
          <span>
            ({totalCells > 0 ? Math.round((occupiedCount / totalCells) * 100) : 0}%)
          </span>
        </div>
      </div>

      <div className="shelf-canvas-grid">
        {rows.map((rowNum) => {
          const numCols = rowColsMap[rowNum] || colsCount;
          const cols = Array.from({ length: numCols }, (_, i) => i + 1);

          return (
            <div key={rowNum} className="shelf-canvas-row">
              <div className="shelf-row-label">R{rowNum}</div>
              <div className="shelf-cells-row">
                {cols.map((colNum) => {
                  const locId = makeSlotName(floor, shelf, rowNum, colNum, side);
                  const cell = cellsData[locId];
                  const isOccupied = !!(cell && cell.items && cell.items.length > 0);
                  const itemCount = cell ? cell.items.length : 0;
                  const isSelected = selectedRow === rowNum && selectedCol === colNum;

                  return (
                    <div
                      key={colNum}
                      className={`shelf-cell ${isOccupied ? 'occupied' : ''} ${
                        isSelected ? 'selected' : ''
                      }`}
                      onClick={() => onCellClick?.(rowNum, colNum, locId)}
                      title={`${locId} ${isOccupied ? `(${itemCount} items)` : '(Empty)'}`}
                    >
                      <span className="shelf-cell-num">{colNum}</span>
                      {isOccupied && (
                        <span className="shelf-cell-badge">{itemCount}</span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
