import React from 'react';
import { ShelfCanvas } from '../components/ShelfCanvas';
import { getShelfCode } from '../utils/coordinates';
import { useShelfBrowserController } from '../controllers/useShelfBrowserController';

export const ShelfBrowserView: React.FC<{ active: boolean }> = React.memo(({ active }: { active: boolean }) => {
  const {
    shelves,
    selectedShelf,
    cellsData,
    selectedCellLoc,
    selectedRow,
    selectedCol,
    loadShelfCells,
    handleCellClick,
    selectedCell,
    items,
    totalUnits,
    occupiedCount,
  } = useShelfBrowserController(active);
  return (
    <div className="view-container">
      <div className="panel">
        <div className="browser-toolbar">
          <div className="browser-toolbar-controls">
            <label className="form-label" htmlFor="browser-shelf-select">Existing shelf</label>
            <select
              id="browser-shelf-select"
              className="input-select"
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

          <div className="browser-toolbar-stats">
            <span>Occupied <strong>{occupiedCount}</strong></span>
            <span>Units <strong>{totalUnits}</strong></span>
            <span className="muted">Read only</span>
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
                <dl className="browser-cell-facts">
                  <div><dt>Row</dt><dd>{selectedRow}</dd></div>
                  <div><dt>Column</dt><dd>{selectedCol}</dd></div>
                  <div><dt>Status</dt><dd className={items.length > 0 ? 'occupied' : ''}>{items.length > 0 ? 'Occupied' : 'Empty'}</dd></div>
                </dl>

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
});
