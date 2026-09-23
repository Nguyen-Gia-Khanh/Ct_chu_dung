import React from 'react';
import { useExceptionsController } from '../controllers/useExceptionsController';

export const ExceptionsView: React.FC<{ active: boolean }> = React.memo(({ active }: { active: boolean }) => {
  const {
    productId, setProductId, stockQty, setStockQty,
    floor, setFloor, side, setSide, shelf, setShelf, row, setRow, col, setCol,
    loadedSlotName, loadedSlotId, loadedSlotItems, loadedSlotMessage,
    onHandSearch, setOnHandSearch, pendingItems, statusMessage, isBusy,
    handleLoadAddress, handleAssignException, handleAppendToCSV, filteredOnHand,
  } = useExceptionsController(active);

  return (
    <div className="exceptions-view">
      <div className="exceptions-intro">
        <div>
          <strong>Special exceptions and multi-location products</strong>
          <p>Assign stock to an exact address. New products stay staged until you append them to CSV.</p>
        </div>
        <span className="count-label">{pendingItems.length} staged update{pendingItems.length === 1 ? '' : 's'}</span>
      </div>

      {statusMessage && <div className="inline-status" role="status">{statusMessage}</div>}

      <div className="exceptions-columns">
        <div className="exceptions-stack">
          <section className="panel exceptions-form-panel">
            <div className="panel-header"><span className="panel-title">Assign a product</span></div>
            <div className="panel-body">
              <label className="form-group">
                <span className="form-label">Product ID or barcode</span>
                <input
                  type="text" className="input-text font-mono" value={productId}
                  onChange={(event) => setProductId(event.target.value)}
                  onKeyDown={(event) => { if (event.key === 'Enter') handleAssignException(); }}
                  placeholder="Scan or enter a product ID"
                />
              </label>

              <div className="exceptions-address-fields">
                <label className="form-group"><span className="form-label">Floor</span><input className="input-text font-mono" value={floor} onChange={(event) => setFloor(event.target.value)} /></label>
                <label className="form-group"><span className="form-label">Side</span><input className="input-text font-mono" value={side} onChange={(event) => setSide(event.target.value)} /></label>
                <label className="form-group"><span className="form-label">Shelf</span><input className="input-text font-mono" value={shelf} onChange={(event) => setShelf(event.target.value)} /></label>
                <label className="form-group"><span className="form-label">Row</span><input type="number" min="1" className="input-text font-mono" value={row} onChange={(event) => setRow(event.target.value)} /></label>
                <label className="form-group"><span className="form-label">Cell</span><input type="number" min="1" className="input-text font-mono" value={col} onChange={(event) => setCol(event.target.value)} /></label>
                <button type="button" className="btn btn-secondary" onClick={handleLoadAddress}>Load address</button>
              </div>

              <div className={`exceptions-address-result ${loadedSlotId ? 'resolved' : ''}`} role="status">{loadedSlotMessage}</div>

              <div className="exceptions-assign-row">
                <label className="form-group"><span className="form-label">Stock quantity (optional)</span><input className="input-text font-mono" value={stockQty} onChange={(event) => setStockQty(event.target.value)} placeholder="Optional" /></label>
                <button type="button" className="btn btn-primary" onClick={handleAssignException} disabled={isBusy}>Assign to address</button>
              </div>
            </div>
          </section>

          <section className="panel exceptions-list-panel">
            <div className="panel-header">
              <span className="panel-title">Shared on-hand products</span>
              <input className="input-text exceptions-search" value={onHandSearch} onChange={(event) => setOnHandSearch(event.target.value)} placeholder="Search products" aria-label="Search on-hand products" />
            </div>
            <div className="exceptions-table-scroll">
              <table className="data-table" aria-label="Shared on-hand products">
                <colgroup><col style={{ width: '31%' }} /><col style={{ width: '54%' }} /><col style={{ width: '15%' }} /></colgroup>
                <thead><tr><th>Product ID</th><th>Product name</th><th className="numeric">Stock</th></tr></thead>
                <tbody>
                  {filteredOnHand.map((item) => (
                    <tr key={item.product_id} className={`selectable-row ${productId === item.product_id ? 'selected' : ''}`} onClick={() => {
                      setProductId(item.product_id);
                      if (item.stock_qty !== null && item.stock_qty !== undefined) setStockQty(String(item.stock_qty));
                    }}>
                      <td className="font-mono">{item.product_id}</td><td className="truncate-cell" title={item.product_name}>{item.product_name}</td>
                      <td className="numeric">{item.stock_qty ?? ''}</td>
                    </tr>
                  ))}
                  {filteredOnHand.length === 0 && <tr><td colSpan={3} className="empty-table">No on-hand products found.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <div className="exceptions-stack">
          <section className="panel exceptions-list-panel">
            <div className="panel-header"><span className="panel-title">Loaded cell contents</span>{loadedSlotName && <span className="location-text">{loadedSlotName}</span>}</div>
            <div className="exceptions-table-scroll">
              <table className="data-table" aria-label="Loaded cell contents">
                <colgroup><col style={{ width: '26%' }} /><col style={{ width: '36%' }} /><col style={{ width: '12%' }} /><col style={{ width: '26%' }} /></colgroup>
                <thead><tr><th>Product ID</th><th>Product name</th><th className="numeric">Stock</th><th>Assigned</th></tr></thead>
                <tbody>
                  {loadedSlotItems.map((item, index) => (
                    <tr key={`${item.product_id}-${index}`}>
                      <td className="font-mono">{item.product_id}</td><td className="truncate-cell" title={item.product_name}>{item.product_name}</td>
                      <td className="numeric">{item.stock_qty ?? ''}</td><td className="muted-cell">{item.assigned_at}</td>
                    </tr>
                  ))}
                  {loadedSlotItems.length === 0 && <tr><td colSpan={4} className="empty-table">{loadedSlotId ? 'Cell is empty.' : 'Load an address to inspect its contents.'}</td></tr>}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel exceptions-list-panel">
            <div className="panel-header">
              <span className="panel-title">Pending CSV updates</span>
              <button type="button" className="btn btn-primary btn-sm" onClick={handleAppendToCSV} disabled={isBusy || pendingItems.length === 0}>Append to CSV</button>
            </div>
            <div className="exceptions-table-scroll">
              <table className="data-table" aria-label="Pending CSV updates">
                <colgroup><col style={{ width: '25%' }} /><col style={{ width: '33%' }} /><col style={{ width: '20%' }} /><col style={{ width: '22%' }} /></colgroup>
                <thead><tr><th>Product ID</th><th>Product name</th><th>Target cell</th><th>Staged at</th></tr></thead>
                <tbody>
                  {pendingItems.map((item) => (
                    <tr key={item.id}>
                      <td className="font-mono">{item.product_id}</td><td className="truncate-cell" title={item.product_name}>{item.product_name}</td>
                      <td className="font-mono">{item.slot_name}</td><td className="muted-cell">{item.created_at.replace('T', ' ')}</td>
                    </tr>
                  ))}
                  {pendingItems.length === 0 && <tr><td colSpan={4} className="empty-table">No exceptions staged.</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="panel-note">New products remain staged until you append them to a CSV file.</div>
          </section>
        </div>
      </div>
    </div>
  );
});
