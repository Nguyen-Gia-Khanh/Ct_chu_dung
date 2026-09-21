import React, { useState, useEffect } from 'react';
import { Shelf, ShelfCell } from '../types';
import { ApiService } from '../services/api';
import { ShelfCanvas } from '../components/ShelfCanvas';
import { getShelfCode } from '../utils/coordinates';

export const ShelfBrowserView: React.FC = () => {
  const [shelves, setShelves] = useState<Shelf[]>([]);
  const [selectedShelf, setSelectedShelf] = useState<Shelf | null>(null);
  const [cellsData, setCellsData] = useState<Record<string, ShelfCell>>({});
  const [selectedCellLoc, setSelectedCellLoc] = useState<string | null>(null);
  const [selectedRow, setSelectedRow] = useState<number | null>(null);
  const [selectedCol, setSelectedCol] = useState<number | null>(null);

  useEffect(() => {
    loadShelves();
  }, []);

  const loadShelves = async () => {
    const list = await ApiService.getShelves();
    setShelves(list);
    if (list.length > 0) {
      loadShelfCells(list[0]);
    }
  };

  const loadShelfCells = async (shelf: Shelf) => {
    setSelectedShelf(shelf);
    const code = getShelfCode(shelf.floor, shelf.side, shelf.shelf);
    const cells = await ApiService.getShelfCells(code);
    setCellsData(cells);
    setSelectedCellLoc(null);
    setSelectedRow(null);
    setSelectedCol(null);
  };

  const handleCellClick = (row: number, col: number, locId: string) => {
    setSelectedRow(row);
    setSelectedCol(col);
    setSelectedCellLoc(locId);
  };

  const selectedCell = selectedCellLoc ? cellsData[selectedCellLoc] : null;
  const items = selectedCell ? selectedCell.items : [];

  // Stats
  let totalUnits = 0;
  let occupiedCount = 0;
  Object.values(cellsData).forEach((cell) => {
    if (cell.items && cell.items.length > 0) {
      occupiedCount++;
      totalUnits += cell.total_quantity;
    }
  });

  return (
    <div className="view-container">
      <div className="panel" style={{ marginBottom: '0.4rem' }}>
        <div
          style={{
            padding: '0.45rem 0.75rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '0.75rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <label className="form-label" style={{ margin: 0 }}>
              Existing shelf:
            </label>
            <select
              className="input-select"
              style={{ fontWeight: 600, minWidth: '220px' }}
              value={selectedShelf ? selectedShelf.id : ''}
              onChange={(e) => {
                const found = shelves.find((s) => s.id === parseInt(e.target.value, 10));
                if (found) loadShelfCells(found);
              }}
            >
              {shelves.map((s) => (
                <option key={s.id} value={s.id}>
                  {getShelfCode(s.floor, s.side, s.shelf)} ({s.rows_count} Rows × {s.default_cols} Cols)
                </option>
              ))}
            </select>
            <button className="btn btn-secondary btn-sm" onClick={() => selectedShelf && loadShelfCells(selectedShelf)}>
              Refresh
            </button>
          </div>

          <div style={{ display: 'flex', gap: '1.25rem', fontSize: '12px', color: 'var(--text-secondary)' }}>
            <div>
              Occupied: <strong style={{ color: 'var(--success)' }}>{occupiedCount}</strong> cells
            </div>
            <div>
              Total Products: <strong>{totalUnits}</strong> units
            </div>
            <div style={{ color: 'var(--text-muted)' }}>Read-only view</div>
          </div>
        </div>
      </div>

      <div className="split-pane right-heavy">
        {/* Left: 2D Shelf Grid */}
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">
              {selectedShelf ? getShelfCode(selectedShelf.floor, selectedShelf.side, selectedShelf.shelf) : 'Shelf'} Layout
            </span>
            {selectedCellLoc && (
              <span className="loc-pill assigned">
                Selected: {selectedCellLoc}
              </span>
            )}
          </div>

          <div className="panel-body">
            {selectedShelf ? (
              <ShelfCanvas
                floor={selectedShelf.floor}
                side={selectedShelf.side}
                shelf={selectedShelf.shelf}
                rowsCount={selectedShelf.rows_count}
                colsCount={selectedShelf.default_cols}
                rowColsMap={selectedShelf.custom_row_cols}
                cellsData={cellsData}
                selectedRow={selectedRow}
                selectedCol={selectedCol}
                onCellClick={handleCellClick}
              />
            ) : (
              <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '2rem' }}>
                No shelf selected.
              </div>
            )}
          </div>
        </div>

        {/* Right: Cell Details */}
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">
              Cell Details: {selectedCellLoc || 'Select a Cell'}
            </span>
            {selectedCellLoc && (
              <span style={{ fontSize: '11.5px', color: 'var(--text-secondary)' }}>
                {items.length} item(s) / {selectedCell?.total_quantity || 0} units
              </span>
            )}
          </div>

          <div className="panel-body">
            {selectedCellLoc ? (
              <div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.4rem', marginBottom: '0.6rem' }}>
                  <div style={{ background: 'var(--bg-subtle)', padding: '0.4rem', borderRadius: '2px' }}>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Row (Ground Up)</div>
                    <div style={{ fontSize: '13px', fontWeight: 600 }}>Row {selectedRow}</div>
                  </div>
                  <div style={{ background: 'var(--bg-subtle)', padding: '0.4rem', borderRadius: '2px' }}>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Slot / Column</div>
                    <div style={{ fontSize: '13px', fontWeight: 600 }}>Col {selectedCol}</div>
                  </div>
                  <div style={{ background: 'var(--bg-subtle)', padding: '0.4rem', borderRadius: '2px' }}>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Status</div>
                    <div style={{ fontSize: '13px', fontWeight: 600, color: items.length > 0 ? 'var(--success)' : 'var(--text-muted)' }}>
                      {items.length > 0 ? 'Occupied' : 'Empty'}
                    </div>
                  </div>
                </div>

                <div className="table-container">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Product ID</th>
                        <th>Product Name</th>
                        <th>Barcode</th>
                        <th style={{ width: '55px' }}>Qty</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((it) => (
                        <tr key={it.product_id}>
                          <td className="font-mono">
                            <strong>{it.product_id}</strong>
                          </td>
                          <td>{it.product_name}</td>
                          <td className="font-mono">{it.barcode}</td>
                          <td>
                            <strong>{it.quantity}</strong>
                          </td>
                        </tr>
                      ))}
                      {items.length === 0 && (
                        <tr>
                          <td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '1.5rem' }}>
                            Cell is empty.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '3rem 1rem' }}>
                <div>Click on any slot in the shelf grid to view contents.</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
