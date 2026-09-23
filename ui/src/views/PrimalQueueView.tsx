import React, { useRef } from 'react';
import { ShelfCanvas } from '../components/ShelfCanvas';
import { formatProductId, getShelfCode } from '../utils/coordinates';
import { usePrimalQueueController } from '../controllers/usePrimalQueueController';

export const PrimalQueueView: React.FC<{ active: boolean }> = React.memo(({ active }: { active: boolean }) => {
  const queueScrollRef = useRef<HTMLDivElement>(null);
  const catalogScrollRef = useRef<HTMLDivElement>(null);
  const {
    shelves,
    currentShelf,
    cellsData,
    searchQuery,
    selectedCellLoc,
    selectedRow,
    selectedCol,
    selectShelf,
    handleSearchChange,
    handleSelectProduct,
    handleCellClick,
    handleRemoveProduct,
    filteredQueue,
    queueLoading,
    filteredCatalog,
    catalogLoading,
    visibleQueue,
    topSpacerHeight,
    bottomSpacerHeight,
    handleQueueScroll,
    visibleCatalog,
    catalogTopSpacerHeight,
    catalogBottomSpacerHeight,
    handleCatalogScroll,
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
              Search both lists
            </span>
          </div>

          <div className="panel-body primal-products-body">
            <div className="form-group">
              <label className="form-label">Search barcode, product ID, or name</label>
              <div className="input-search-wrapper">
                <input
                  type="text"
                  className="input-text font-mono"
                  placeholder="Scan or type barcode (selects text on focus)..."
                  value={searchQuery}
                  onChange={(e) => {
                    if (queueScrollRef.current) queueScrollRef.current.scrollTop = 0;
                    if (catalogScrollRef.current) catalogScrollRef.current.scrollTop = 0;
                    handleSearchChange(e.target.value);
                  }}
                  onFocus={(e) => e.target.select()}
                  autoFocus
                />
                {searchQuery && (
                  <button className="search-clear-btn" onClick={() => {
                    if (queueScrollRef.current) queueScrollRef.current.scrollTop = 0;
                    if (catalogScrollRef.current) catalogScrollRef.current.scrollTop = 0;
                    handleSearchChange('');
                  }}>
                    &times;
                  </button>
                )}
              </div>
            </div>

            <section className="primal-list-section">
              <div className="list-section-heading"><strong>Primal Product Queue</strong><span>{filteredQueue.length} products</span></div>
            <div
              ref={queueScrollRef}
              className="table-container queue-table-container"
              onScroll={(e) => handleQueueScroll(e.currentTarget.scrollTop, e.currentTarget.clientHeight)}
            >
              <table className="data-table primal-queue-table" aria-label="Primal product queue">
                <colgroup>
                  <col style={{ width: '23%' }} />
                  <col style={{ width: '39%' }} />
                  <col style={{ width: '9%' }} />
                  <col style={{ width: '19%' }} />
                  <col style={{ width: '10%' }} />
                </colgroup>
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
                  {topSpacerHeight > 0 && <tr aria-hidden="true" className="queue-spacer"><td colSpan={5} style={{ height: topSpacerHeight }} /></tr>}
                  {visibleQueue.map((item) => (
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
                      <td title={item.product_name}>{item.product_name}</td>
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
                  {bottomSpacerHeight > 0 && <tr aria-hidden="true" className="queue-spacer"><td colSpan={5} style={{ height: bottomSpacerHeight }} /></tr>}
                  {filteredQueue.length === 0 && (
                    <tr>
                      <td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                        {queueLoading ? 'Loading queue…' : 'No items found.'}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            </section>
            <section className="primal-list-section">
              <div className="list-section-heading"><strong>Full Product Catalog</strong><span>{filteredCatalog.length} products</span></div>
              <div
                ref={catalogScrollRef}
                className="table-container queue-table-container"
                onScroll={(e) => handleCatalogScroll(e.currentTarget.scrollTop, e.currentTarget.clientHeight)}
              >
                <table className="data-table primal-queue-table" aria-label="Full product catalog">
                  <colgroup><col style={{ width: '26%' }} /><col style={{ width: '55%' }} /><col style={{ width: '19%' }} /></colgroup>
                  <thead><tr><th>Product ID</th><th>Product Name</th><th>Location</th></tr></thead>
                  <tbody>
                    {catalogTopSpacerHeight > 0 && <tr aria-hidden="true" className="queue-spacer"><td colSpan={3} style={{ height: catalogTopSpacerHeight }} /></tr>}
                    {visibleCatalog.map((item) => (
                      <tr key={item.product_id} onClick={() => handleSelectProduct(item.loc_id || undefined)} className={selectedCellLoc && item.loc_id === selectedCellLoc ? 'selected' : ''}>
                        <td className="font-mono"><strong>{item.product_id}</strong></td>
                        <td title={item.product_name}>{item.product_name}</td>
                        <td>{item.loc_id ? <span className="loc-pill assigned">{item.loc_id}</span> : <span className="loc-pill">Unassigned</span>}</td>
                      </tr>
                    ))}
                    {catalogBottomSpacerHeight > 0 && <tr aria-hidden="true" className="queue-spacer"><td colSpan={3} style={{ height: catalogBottomSpacerHeight }} /></tr>}
                    {filteredCatalog.length === 0 && <tr><td colSpan={3} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>{catalogLoading ? 'Loading catalog…' : 'No catalog products found.'}</td></tr>}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </div>

        {/* Right Side: Shelf View */}
        <div className="panel">
          <div className="panel-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <span className="panel-title">Shelf View:</span>
              <select
                className="input-select"
                style={{ width: 'auto', minWidth: '180px', fontWeight: 600 }}
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
                {queueLoading ? 'Loading shelves…' : 'No shelves created.'}
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
