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

  // Compute stats
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
      <div className="panel" style={{ marginBottom: '0.75rem' }}>
        <div
          style={{
            padding: '0.75rem 1rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '1rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <label className="form-label" style={{ margin: 0 }}>
              Select Shelf to Browse:
            </label>
            <select
              className="input-select"
              style={{ fontWeight: 600, minWidth: '180px' }}
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
          </div>

          <div style={{ display: 'flex', gap: '1.5rem', fontSize: '0.85rem' }}>
            <div>
              Occupied Cells:{' '}
              <strong style={{ color: '#2e7d32' }}>{occupiedCount}</strong>
            </div>
            <div>
              Total Products Stored: <strong>{totalUnits}</strong> units
            </div>
          </div>
        </div>
      </div>

      <div className="split-pane right-heavy">
        {/* Left Side: 2D Interactive Shelf Canvas */}
        <div className="panel">
          <div className="panel-header">
            <h2 className="panel-title">
              🏢 {selectedShelf ? getShelfCode(selectedShelf.floor, selectedShelf.side, selectedShelf.shelf) : 'Shelf'} Layout
            </h2>
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

        {/* Right Side: Cell Contents & Details */}
        <div className="panel">
          <div className="panel-header">
            <h2 className="panel-title">
              📋 Cell Details: {selectedCellLoc || 'Select a Cell'}
            </h2>
            {selectedCellLoc && (
              <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                {items.length} item(s) / {selectedCell?.total_quantity || 0} units
              </span>
            )}
          </div>

          <div className="panel-body">
            {selectedCellLoc ? (
              <div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem', marginBottom: '1rem' }}>
                  <div style={{ background: '#f8fafc', padding: '0.5rem', borderRadius: '4px' }}>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>ROW (GROUND UP)</div>
                    <div style={{ fontSize: '1.1rem', fontWeight: 700 }}>Row {selectedRow}</div>
                  </div>
                  <div style={{ background: '#f8fafc', padding: '0.5rem', borderRadius: '4px' }}>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>COLUMN / CELL</div>
                    <div style={{ fontSize: '1.1rem', fontWeight: 700 }}>Col {selectedCol}</div>
                  </div>
                  <div style={{ background: '#f8fafc', padding: '0.5rem', borderRadius: '4px' }}>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>STATUS</div>
                    <div style={{ fontSize: '0.9rem', fontWeight: 600, color: items.length > 0 ? '#15803d' : '#64748b' }}>
                      {items.length > 0 ? 'Occupied' : 'Empty'}
                    </div>
                  </div>
                </div>

                <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.4rem' }}>
                  Products Stored in this Cell:
                </div>
                <div className="table-container">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Product ID</th>
                        <th>Product Name</th>
                        <th>Barcode</th>
                        <th>Qty</th>
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
                          <td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '2rem' }}>
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
                <div style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>🔍</div>
                <div>Click on any slot in the shelf grid to inspect its contents.</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
