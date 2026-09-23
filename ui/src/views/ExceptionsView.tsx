import React from 'react';
import { useExceptionsController } from '../controllers/useExceptionsController';

export const ExceptionsView: React.FC<{ active: boolean }> = React.memo(({ active }: { active: boolean }) => {
  const {
    productId,
    setProductId,
    stockQty,
    setStockQty,
    floor,
    setFloor,
    side,
    setSide,
    shelf,
    setShelf,
    row,
    setRow,
    col,
    setCol,
    loadedSlotName,
    loadedSlotId,
    loadedSlotItems,
    loadedSlotMessage,
    onHandSearch,
    setOnHandSearch,
    pendingItems,
    statusMessage,
    isBusy,
    handleLoadAddress,
    handleAssignException,
    handleAppendToCSV,
    filteredOnHand,
  } = useExceptionsController(active);
  return (
    <div className="tab-pane-container" style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '10px' }}>
      {/* Top Header Bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px', borderBottom: '1px solid #d0d7de', paddingBottom: '8px' }}>
        <div>
          <h2 style={{ fontSize: '15px', fontWeight: 600, margin: '0 0 4px 0', color: '#1f2328' }}>
            Special Exceptions & Multi-Location Products
          </h2>
          <div style={{ fontSize: '12px', color: '#656d76' }}>
            Assign items requiring multiple locations or stage unregistered products safely. Staged items will not modify CSV files until appended.
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{ fontSize: '12px', fontWeight: 600, color: '#0969da' }}>
            {pendingItems.length} staged CSV update(s)
          </span>
          <button
            className="vscode-btn vscode-btn-primary"
            onClick={handleAppendToCSV}
            disabled={isBusy || pendingItems.length === 0}
            style={{ fontSize: '12px', padding: '4px 12px' }}
          >
            Append back to CSV
          </button>
        </div>
      </div>

      <div className="address-status-label">{statusMessage}</div>

      {/* Main 2-Column Paned Area */}
      <div style={{ display: 'flex', gap: '12px', flex: 1, minHeight: 0 }}>
        {/* Left Column: Input and Address Assignment + On-Hand Queue */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '10px', minWidth: 0 }}>
          {/* Assignment Box */}
          <div style={{ background: '#ffffff', border: '1px solid #d0d7de', borderRadius: '4px', padding: '10px' }}>
            <div style={{ fontSize: '12px', fontWeight: 600, marginBottom: '8px', color: '#1f2328' }}>
              Assign Special Exception / Unregistered Product
            </div>

            {/* Product ID Entry */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
              <label style={{ fontSize: '12px', minWidth: '130px', fontWeight: 500 }}>Product ID / Barcode:</label>
              <input
                type="text"
                className="vscode-input"
                value={productId}
                onChange={(e) => setProductId(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleAssignException(); }}
                placeholder="e.g. 06410-KAN-640 or new code"
                style={{ flex: 1, height: '26px' }}
              />
            </div>

            {/* Address Selector */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px', flexWrap: 'wrap' }}>
              <span style={{ fontSize: '12px', fontWeight: 500 }}>Floor:</span>
              <input
                type="text"
                className="vscode-input"
                value={floor}
                onChange={(e) => setFloor(e.target.value)}
                style={{ width: '40px', height: '24px', textAlign: 'center' }}
              />
              <span style={{ fontSize: '12px', fontWeight: 500 }}>Side:</span>
              <input
                type="text"
                className="vscode-input"
                value={side}
                onChange={(e) => setSide(e.target.value)}
                style={{ width: '40px', height: '24px', textAlign: 'center' }}
              />
              <span style={{ fontSize: '12px', fontWeight: 500 }}>Shelf:</span>
              <input
                type="text"
                className="vscode-input"
                value={shelf}
                onChange={(e) => setShelf(e.target.value)}
                style={{ width: '45px', height: '24px', textAlign: 'center' }}
              />
              <span style={{ fontSize: '12px', fontWeight: 500 }}>Row:</span>
              <input
                type="number"
                min="1"
                className="vscode-input"
                value={row}
                onChange={(e) => setRow(e.target.value)}
                style={{ width: '45px', height: '24px', textAlign: 'center' }}
              />
              <span style={{ fontSize: '12px', fontWeight: 500 }}>Cell:</span>
              <input
                type="number"
                min="1"
                className="vscode-input"
                value={col}
                onChange={(e) => setCol(e.target.value)}
                style={{ width: '45px', height: '24px', textAlign: 'center' }}
              />
              <button
                className="vscode-btn"
                onClick={handleLoadAddress}
                style={{ height: '24px', padding: '0 8px', fontSize: '11px', marginLeft: '4px' }}
              >
                Load address
              </button>
            </div>

            {/* Loaded Address Status */}
            <div style={{ fontSize: '11px', fontWeight: 600, color: loadedSlotId ? '#0969da' : '#656d76', marginBottom: '8px' }}>
              {loadedSlotMessage}
            </div>

            {/* Quantity and Assign Button */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <label style={{ fontSize: '12px', fontWeight: 500 }}>Stock Qty (optional):</label>
              <input
                type="text"
                className="vscode-input"
                value={stockQty}
                onChange={(e) => setStockQty(e.target.value)}
                placeholder="null"
                style={{ width: '60px', height: '26px', textAlign: 'center' }}
              />
              <button
                className="vscode-btn vscode-btn-primary"
                onClick={handleAssignException}
                disabled={isBusy}
                style={{ flex: 1, height: '28px', fontSize: '12px', fontWeight: 600 }}
              >
                Assign to loaded address
              </button>
            </div>
          </div>

          {/* Shared On-Hand Products */}
          <div style={{ background: '#ffffff', border: '1px solid #d0d7de', borderRadius: '4px', padding: '8px', flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
              <span style={{ fontSize: '12px', fontWeight: 600, color: '#1f2328' }}>Shared On-Hand Products</span>
              <input
                type="text"
                className="vscode-input"
                value={onHandSearch}
                onChange={(e) => setOnHandSearch(e.target.value)}
                placeholder="Search on-hand..."
                style={{ width: '180px', height: '22px', fontSize: '11px' }}
              />
            </div>
            <div style={{ flex: 1, overflowY: 'auto', border: '1px solid #e1e4e8', borderRadius: '2px' }}>
              <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                <thead>
                  <tr style={{ background: '#f6f8fa', borderBottom: '1px solid #d0d7de', position: 'sticky', top: 0 }}>
                    <th style={{ textAlign: 'left', padding: '4px 6px' }}>Product ID</th>
                    <th style={{ textAlign: 'left', padding: '4px 6px' }}>Product Name</th>
                    <th style={{ textAlign: 'right', padding: '4px 6px' }}>Stock</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredOnHand.map((item) => (
                    <tr
                      key={item.product_id}
                      onClick={() => {
                        setProductId(item.product_id);
                        if (item.stock_qty !== null && item.stock_qty !== undefined) {
                          setStockQty(String(item.stock_qty));
                        }
                      }}
                      style={{
                        cursor: 'pointer',
                        background: productId === item.product_id ? '#e8f0fe' : 'transparent',
                        borderBottom: '1px solid #f0f2f5',
                      }}
                    >
                      <td style={{ padding: '4px 6px', fontWeight: 500 }}>{item.product_id}</td>
                      <td style={{ padding: '4px 6px', maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {item.product_name}
                      </td>
                      <td style={{ padding: '4px 6px', textAlign: 'right' }}>
                        {item.stock_qty !== null && item.stock_qty !== undefined ? item.stock_qty : ''}
                      </td>
                    </tr>
                  ))}
                  {filteredOnHand.length === 0 && (
                    <tr>
                      <td colSpan={3} style={{ textAlign: 'center', padding: '12px', color: '#8c959f' }}>
                        No on-hand products found.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Right Column: Loaded Cell Contents & Staged CSV Updates */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '10px', minWidth: 0 }}>
          {/* Loaded Cell Contents */}
          <div style={{ background: '#ffffff', border: '1px solid #d0d7de', borderRadius: '4px', padding: '8px', flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div style={{ fontSize: '12px', fontWeight: 600, marginBottom: '6px', color: '#1f2328' }}>
              Current Loaded Cell Contents {loadedSlotName ? `(${loadedSlotName})` : ''}
            </div>
            <div style={{ flex: 1, overflowY: 'auto', border: '1px solid #e1e4e8', borderRadius: '2px' }}>
              <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                <thead>
                  <tr style={{ background: '#f6f8fa', borderBottom: '1px solid #d0d7de', position: 'sticky', top: 0 }}>
                    <th style={{ textAlign: 'left', padding: '4px 6px' }}>Product ID</th>
                    <th style={{ textAlign: 'left', padding: '4px 6px' }}>Product Name</th>
                    <th style={{ textAlign: 'right', padding: '4px 6px' }}>Stock</th>
                    <th style={{ textAlign: 'left', padding: '4px 6px' }}>Assigned Time</th>
                  </tr>
                </thead>
                <tbody>
                  {loadedSlotItems.map((item, idx) => (
                    <tr key={`${item.product_id}-${idx}`} style={{ borderBottom: '1px solid #f0f2f5' }}>
                      <td style={{ padding: '4px 6px', fontWeight: 500 }}>{item.product_id}</td>
                      <td style={{ padding: '4px 6px', maxWidth: '160px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {item.product_name}
                      </td>
                      <td style={{ padding: '4px 6px', textAlign: 'right' }}>
                        {item.stock_qty !== null && item.stock_qty !== undefined ? item.stock_qty : ''}
                      </td>
                      <td style={{ padding: '4px 6px', fontSize: '11px', color: '#555' }}>
                        {item.assigned_at}
                      </td>
                    </tr>
                  ))}
                  {loadedSlotItems.length === 0 && (
                    <tr>
                      <td colSpan={4} style={{ textAlign: 'center', padding: '16px', color: '#8c959f' }}>
                        {loadedSlotId ? 'Cell is currently empty.' : 'Load a shelf address to inspect its contents.'}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Staged CSV Updates (wait_to_update_csv) */}
          <div style={{ background: '#ffffff', border: '1px solid #d0d7de', borderRadius: '4px', padding: '8px', flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
              <span style={{ fontSize: '12px', fontWeight: 600, color: '#1f2328' }}>
                Wait to Update Back to CSV (Staged)
              </span>
              <button
                className="vscode-btn vscode-btn-primary"
                onClick={handleAppendToCSV}
                disabled={isBusy || pendingItems.length === 0}
                style={{ fontSize: '11px', padding: '2px 8px' }}
              >
                Append back to CSV
              </button>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', border: '1px solid #e1e4e8', borderRadius: '2px' }}>
              <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                <thead>
                  <tr style={{ background: '#f6f8fa', borderBottom: '1px solid #d0d7de', position: 'sticky', top: 0 }}>
                    <th style={{ textAlign: 'left', padding: '4px 6px' }}>Product ID</th>
                    <th style={{ textAlign: 'left', padding: '4px 6px' }}>Product Name</th>
                    <th style={{ textAlign: 'left', padding: '4px 6px' }}>Target Cell</th>
                    <th style={{ textAlign: 'left', padding: '4px 6px' }}>Staged At</th>
                  </tr>
                </thead>
                <tbody>
                  {pendingItems.map((item) => (
                    <tr key={item.id} style={{ borderBottom: '1px solid #f0f2f5' }}>
                      <td style={{ padding: '4px 6px', fontWeight: 500 }}>{item.product_id}</td>
                      <td style={{ padding: '4px 6px', color: '#656d76' }}>{item.product_name}</td>
                      <td style={{ padding: '4px 6px', fontWeight: 600, color: '#0969da' }}>{item.slot_name}</td>
                      <td style={{ padding: '4px 6px', fontSize: '11px', color: '#555' }}>
                        {item.created_at.replace('T', ' ')}
                      </td>
                    </tr>
                  ))}
                  {pendingItems.length === 0 && (
                    <tr>
                      <td colSpan={4} style={{ textAlign: 'center', padding: '16px', color: '#8c959f' }}>
                        No pending exceptions staged.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <div style={{ fontSize: '11px', color: '#656d76', marginTop: '6px' }}>
              Newly added exception products wait here safely. Appending will write them with name "Exc - added later" to your chosen CSV file.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
});
