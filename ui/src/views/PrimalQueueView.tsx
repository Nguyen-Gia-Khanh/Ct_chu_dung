import React from 'react';
import { ShelfCanvas } from '../components/ShelfCanvas';
import { getShelfCode } from '../utils/coordinates';
import { usePrimalQueueController } from '../controllers/usePrimalQueueController';

export const PrimalQueueView: React.FC<{ active: boolean }> = React.memo(({ active }: { active: boolean }) => {
  const {
    shelves,
    currentShelf,
    cellsData,
    searchQuery,
    setSearchQuery,
    selectedCellLoc,
    selectedRow,
    selectedCol,
    selectShelf,
    handleSearchChange,
    handleSelectProduct,
    handleCellClick,
    handleRemoveProduct,
    filteredQueue,
    activeCellItems,
  } = usePrimalQueueController(active);
  return (
    <div className="view-container">
      <div className="split-pane left-heavy">
        {/* Left Side: Products (Primal Queue & Full Catalog) */}
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">Products (Primal Queue & Full Catalog)</span>
            <span style={{ fontSize: '11.5px', color: 'var(--text-secondary)' }}>
              {filteredQueue.length} items
            </span>
          </div>

          <div className="panel-body">
            <div className="form-group">
              <label className="form-label">Search barcode or product ID (auto-formats 5-3-3)</label>
              <div className="input-search-wrapper">
                <input
                  type="text"
                  className="input-text font-mono"
                  placeholder="Scan or type barcode (selects text on focus)..."
                  value={searchQuery}
                  onChange={(e) => handleSearchChange(e.target.value)}
                  onFocus={(e) => e.target.select()}
                  autoFocus
                />
                {searchQuery && (
                  <button className="search-clear-btn" onClick={() => setSearchQuery('')}>
                    &times;
                  </button>
                )}
              </div>
            </div>

            <div className="table-container" style={{ flex: 1, maxHeight: '520px' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Barcode / ID</th>
                    <th>Product Name</th>
                    <th style={{ width: '50px' }}>Qty</th>
                    <th>Location</th>
                    <th style={{ width: '80px' }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredQueue.map((item) => (
                    <tr
                      key={item.barcode}
                      style={{ cursor: 'pointer' }}
                      className={
                        selectedCellLoc && item.target_location === selectedCellLoc ? 'selected' : ''
                      }
                      onClick={() => handleSelectProduct(item.target_location)}
                    >
                      <td className="font-mono">
                        <strong>{formatProductId(item.barcode)}</strong>
                      </td>
                      <td>{item.product_name}</td>
                      <td>{item.quantity}</td>
                      <td>
                        {item.target_location ? (
                          <span className="loc-pill assigned">{item.target_location}</span>
                        ) : (
                          <span className="loc-pill">Pending</span>
                        )}
                      </td>
                      <td>
                        {item.target_location && (
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleSelectProduct(item.target_location);
                            }}
                          >
                            View
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                  {filteredQueue.length === 0 && (
                    <tr>
                      <td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                        No items found.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Right Side: Shelf View */}
        <div className="panel">
          <div className="panel-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <span className="panel-title">Shelf View:</span>
              <select
                className="input-select"
                style={{ height: '24px', padding: '0 0.4rem', fontWeight: 600 }}
                value={currentShelf ? currentShelf.id : ''}
                onChange={(e) => {
                  const s = shelves.find((x) => x.id === parseInt(e.target.value, 10));
                  if (s) selectShelf(s);
                }}
              >
                {shelves.map((s) => (
                  <option key={s.id} value={s.id}>
                    {getShelfCode(s.floor, s.side, s.shelf)} ({s.rows_count}R × {s.default_cols}C)
                  </option>
                ))}
              </select>
            </div>

            {selectedCellLoc && (
              <span className="loc-pill assigned">
                {selectedCellLoc}
              </span>
            )}
          </div>

          <div className="panel-body">
            {currentShelf ? (
              <ShelfCanvas
                floor={currentShelf.floor}
                side={currentShelf.side}
                shelf={currentShelf.shelf}
                rowsCount={currentShelf.rows_count}
                colsCount={currentShelf.default_cols}
                rowColsMap={currentShelf.custom_row_cols}
                cellsData={cellsData}
                selectedRow={selectedRow}
                selectedCol={selectedCol}
                onCellClick={handleCellClick}
              />
            ) : (
              <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '2rem' }}>
                No shelves created.
              </div>
            )}

            {/* Cell Contents */}
            <div style={{ marginTop: '0.4rem' }}>
              <div
                style={{
                  fontSize: '11.5px',
                  fontWeight: 600,
                  marginBottom: '0.3rem',
                  display: 'flex',
                  justifyContent: 'space-between',
                  color: 'var(--text-secondary)',
                }}
              >
                <span>
                  Contents in <strong className="font-mono">{selectedCellLoc || 'None'}</strong>:
                </span>
                <span>
                  {activeCellItems.length} product(s)
                </span>
              </div>

              <div className="table-container" style={{ maxHeight: '180px' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Product ID</th>
                      <th>Product Name</th>
                      <th style={{ width: '55px' }}>Qty</th>
                      <th style={{ width: '60px' }}>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeCellItems.map((item) => (
                      <tr key={item.product_id}>
                        <td className="font-mono">
                          <strong>{item.product_id}</strong>
                        </td>
                        <td>{item.product_name}</td>
                        <td>{item.quantity}</td>
                        <td>
                          <button
                            className="btn btn-danger btn-sm"
                            onClick={() => handleRemoveProduct(item.product_id)}
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                    ))}
                    {activeCellItems.length === 0 && (
                      <tr>
                        <td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                          {selectedCellLoc
                            ? 'Cell is empty.'
                            : 'Click a cell above to view contents.'}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
});
