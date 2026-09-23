import React from 'react';
import { useLocationAssignmentController } from '../controllers/useLocationAssignmentController';

export const LocationAssignmentView: React.FC<{ active: boolean }> = React.memo(({ active }: { active: boolean }) => {
  const {
    catalog,
    onHandProducts,
    selectedQueueIds,
    setSelectedQueueIds,
    selectedCatalogIds,
    setSelectedCatalogIds,
    selectedOnHandIds,
    setSelectedOnHandIds,
    selectedContentIds,
    setSelectedContentIds,
    lastQueueIdRef,
    lastCatIdRef,
    lastHandIdRef,
    lastContentIdRef,
    searchQuery,
    setSearchQuery,
    searchLocationText,
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
    loadedSlot,
    loadedContents,
    addressStatusText,
    webBatchMode,
    setWebBatchMode,
    uploadStatusText,
    copyStatusText,
    handleTableSelect,
    handleMoveSelectedToOnHand,
    handleTransferSelectedToQueue,
    handleCatalogDoubleClick,
    handleEditSelectedQuantity,
    handleDequeueOnHand,
    handleLoadAddress,
    handleAssignAddress,
    handleCopyProductId,
    handleModifyLoadedStock,
    handleSelectedToHand,
    handleShelfAllToHand,
    handleModifyLocationWeb,
    handleConnectChrome,
    filteredPending,
    filteredCatalog,
    visiblePending,
    visibleCatalog,
    pendingIds,
    catalogIds,
    onHandIds,
    loadedContentIds,
  } = useLocationAssignmentController(active);
  return (
    <div className="view-container">
      {/* Top Header matching Tkinter */}
      <div className="tab-sub-header">
        <span className="tab-heading">
          Build a persistent on-hand batch, then assign it to one exact shelf address.
        </span>
        <button className="btn btn-secondary btn-sm" onClick={handleConnectChrome}>
          Connect Chrome
        </button>
      </div>

      {/* Main 3-column split pane */}
      <div className="split-pane three-column">
        {/* PANEL 1: Products */}
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">Products</span>
          </div>
          <div className="panel-body" style={{ gap: '8px' }}>
            {/* Box 1: Total unassigned product queue */}
            <div className="group-card" style={{ flex: 1 }}>
              <div className="group-card-title">Total unassigned product queue</div>
              <div className="form-group">
                <label className="form-label">Search code, full name, or shortened name</label>
                <div className="input-search-wrapper">
                  <input
                    type="text"
                    className="input-text"
                    placeholder="Type or scan product ID..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                  />
                  {searchQuery && (
                    <button className="search-clear-btn" onClick={() => setSearchQuery('')}>
                      &times;
                    </button>
                  )}
                </div>
                <div className="search-location-hint">{searchLocationText}</div>
              </div>

              <div className="table-container" style={{ flex: 1, maxHeight: '160px' }}>
                <table className="data-table selectable">
                  <thead>
                    <tr>
                      <th style={{ width: '110px' }}>Product ID</th>
                      <th>Product name</th>
                      <th style={{ width: '65px', textAlign: 'right' }}>Stock</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visiblePending.map((item) => (
                      <tr
                        key={item.code}
                        className={`${selectedQueueIds.includes(item.code) ? 'selected-row' : ''} ${
                          item.returned ? 'returned-row' : ''
                        }`}
                        onClick={(e) => handleTableSelect(item.code, pendingIds, selectedQueueIds, setSelectedQueueIds, lastQueueIdRef, e)}
                      >
                        <td className="font-mono">
                          <strong>{item.code}</strong>
                        </td>
                        <td>{item.name}</td>
                        <td style={{ textAlign: 'right' }}>{item.on_hand != null ? item.on_hand : ''}</td>
                      </tr>
                    ))}
                    {filteredPending.length === 0 && (
                      <tr>
                        <td colSpan={3} style={{ textAlign: 'center', color: 'var(--vscode-text-muted)', padding: '16px' }}>
                          No unassigned products.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              <div className="group-card-footer">
                <span className="count-label">{filteredPending.length.toLocaleString()} products</span>
                <button
                  className="btn btn-secondary"
                  style={{ width: '100%' }}
                  onClick={handleMoveSelectedToOnHand}
                  disabled={selectedQueueIds.length === 0}
                >
                  Move selected → on-hand
                </button>
              </div>
            </div>

            {/* Box 2: Full product catalog */}
            <div className="group-card" style={{ flex: 1 }}>
              <div className="group-card-title">Full product catalog</div>

              <div className="table-container" style={{ flex: 1, maxHeight: '160px' }}>
                <table className="data-table selectable">
                  <thead>
                    <tr>
                      <th style={{ width: '110px' }}>Product ID</th>
                      <th>Product name</th>
                      <th style={{ width: '120px' }}>Location ID</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleCatalog.map((prod) => (
                      <tr
                        key={prod.product_id}
                        className={selectedCatalogIds.includes(prod.product_id) ? 'selected-row' : ''}
                        onClick={(e) => handleTableSelect(prod.product_id, catalogIds, selectedCatalogIds, setSelectedCatalogIds, lastCatIdRef, e)}
                        onDoubleClick={() => handleCatalogDoubleClick(prod.product_id)}
                      >
                        <td className="font-mono">
                          <strong>{prod.product_id}</strong>
                        </td>
                        <td>{prod.product_name}</td>
                        <td>
                          {prod.loc_id ? (
                            <span className="loc-pill assigned">{prod.loc_id}</span>
                          ) : (
                            <span className="loc-pill">Unassigned</span>
                          )}
                        </td>
                      </tr>
                    ))}
                    {filteredCatalog.length === 0 && (
                      <tr>
                        <td colSpan={3} style={{ textAlign: 'center', color: 'var(--vscode-text-muted)', padding: '16px' }}>
                          No catalog products.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              <div className="group-card-footer">
                <span className="count-label">{filteredCatalog.length.toLocaleString()} products</span>
                <button
                  className="btn btn-secondary"
                  style={{ width: '100%' }}
                  onClick={handleTransferSelectedToQueue}
                  disabled={selectedCatalogIds.length === 0}
                >
                  Transfer selected to total queue
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* PANEL 2: On-hand queue and shelf address */}
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">On-hand queue and shelf address</span>
          </div>
          <div className="panel-body" style={{ gap: '8px' }}>
            {/* On-hand Treeview */}
            <div className="table-container" style={{ flex: 1, minHeight: '190px' }}>
              <table className="data-table selectable">
                <thead>
                  <tr>
                    <th style={{ width: '110px' }}>Product ID</th>
                    <th>Product name</th>
                    <th style={{ width: '65px', textAlign: 'right' }}>Stock</th>
                  </tr>
                </thead>
                <tbody>
                  {onHandProducts.map((item) => (
                    <tr
                      key={item.product_id}
                      className={selectedOnHandIds.includes(item.product_id) ? 'selected-row' : ''}
                      onClick={(e) => handleTableSelect(item.product_id, onHandIds, selectedOnHandIds, setSelectedOnHandIds, lastHandIdRef, e)}
                    >
                      <td className="font-mono">
                        <strong>{item.product_id}</strong>
                      </td>
                      <td>{item.product_name}</td>
                      <td style={{ textAlign: 'right' }}>{item.stock_qty != null ? item.stock_qty : ''}</td>
                    </tr>
                  ))}
                  {onHandProducts.length === 0 && (
                    <tr>
                      <td colSpan={3} style={{ textAlign: 'center', color: 'var(--vscode-text-muted)', padding: '24px' }}>
                        0 products ready to assign
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="count-label" style={{ fontWeight: 600 }}>
              {onHandProducts.length} products ready to assign
            </div>

            {/* Hand Action Buttons */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={handleEditSelectedQuantity}
                disabled={selectedOnHandIds.length !== 1}
              >
                Edit selected quantity
              </button>
              <button
                className="btn btn-secondary btn-sm"
                onClick={handleDequeueOnHand}
                disabled={selectedOnHandIds.length === 0}
              >
                Dequeue selected → total queue
              </button>
            </div>

            {/* Shelf Address Card */}
            <div className="group-card" style={{ marginTop: '2px' }}>
              <div className="group-card-title">Shelf address</div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '4px' }}>
                <div className="form-group">
                  <label className="form-label">Floor</label>
                  <input
                    type="text"
                    className="input-text font-mono"
                    value={floor}
                    onChange={(e) => setFloor(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleLoadAddress()}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Side</label>
                  <input
                    type="text"
                    className="input-text font-mono"
                    value={side}
                    onChange={(e) => setSide(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleLoadAddress()}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Shelf</label>
                  <input
                    type="text"
                    className="input-text font-mono"
                    value={shelf}
                    onChange={(e) => setShelf(e.target.value.toUpperCase())}
                    onKeyDown={(e) => e.key === 'Enter' && handleLoadAddress()}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Row</label>
                  <input
                    type="number"
                    min="1"
                    className="input-text font-mono"
                    value={row}
                    onChange={(e) => setRow(parseInt(e.target.value, 10) || 1)}
                    onKeyDown={(e) => e.key === 'Enter' && handleLoadAddress()}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Col / cell</label>
                  <input
                    type="number"
                    min="1"
                    className="input-text font-mono"
                    value={col}
                    onChange={(e) => setCol(parseInt(e.target.value, 10) || 1)}
                    onKeyDown={(e) => e.key === 'Enter' && handleLoadAddress()}
                  />
                </div>
              </div>

              <button
                className="btn btn-secondary"
                style={{ width: '100%', marginTop: '4px' }}
                onClick={handleLoadAddress}
              >
                Load address →
              </button>

              <button
                className="btn btn-primary commit-btn"
                style={{ width: '100%', marginTop: '4px' }}
                onClick={handleAssignAddress}
                disabled={!loadedSlot || onHandProducts.length === 0}
              >
                Assign selected on-hand → loaded address
              </button>

              <div className="address-status-label">{addressStatusText}</div>
            </div>
          </div>
        </div>

        {/* PANEL 3: Loaded address contents */}
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">Loaded address contents</span>
          </div>
          <div className="panel-body" style={{ gap: '8px' }}>
            <div className="slot-heading">
              {loadedSlot ? loadedSlot.slot_name : 'No address loaded'}
            </div>

            <div className="table-container" style={{ flex: 1, minHeight: '220px' }}>
              <table className="data-table selectable">
                <thead>
                  <tr>
                    <th style={{ width: '110px' }}>Product ID</th>
                    <th>Product name</th>
                    <th style={{ width: '55px', textAlign: 'right' }}>Stock</th>
                    <th style={{ width: '150px' }}>Added to shelf</th>
                  </tr>
                </thead>
                <tbody>
                  {loadedContents.map((it) => (
                    <tr
                      key={it.product_id}
                      className={selectedContentIds.includes(it.product_id) ? 'selected-row' : ''}
                      onClick={(e) => handleTableSelect(it.product_id, loadedContentIds, selectedContentIds, setSelectedContentIds, lastContentIdRef, e)}
                      onDoubleClick={() => handleCopyProductId(it.product_id)}
                      title="Double-click to copy Product ID"
                    >
                      <td className="font-mono">
                        <strong>{it.product_id}</strong>
                      </td>
                      <td>{it.product_name}</td>
                      <td style={{ textAlign: 'right' }}>{it.stock_qty != null ? it.stock_qty : ''}</td>
                      <td>{it.assigned_at}</td>
                    </tr>
                  ))}
                  {loadedContents.length === 0 && (
                    <tr>
                      <td colSpan={4} style={{ textAlign: 'center', color: 'var(--vscode-text-muted)', padding: '24px' }}>
                        {loadedSlot ? `Slot ${loadedSlot.slot_name} is empty.` : 'No address loaded.'}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <button
              className="btn btn-secondary"
              style={{ width: '100%' }}
              onClick={handleModifyLoadedStock}
              disabled={selectedContentIds.length !== 1}
            >
              Modify selected stock
            </button>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={handleSelectedToHand}
                disabled={selectedContentIds.length === 0}
              >
                Selected product(s) → on-hand
              </button>
              <button
                className="btn btn-secondary btn-sm"
                onClick={handleShelfAllToHand}
                disabled={!loadedSlot || loadedContents.length === 0}
              >
                Shelf → on-hand (all)
              </button>
            </div>

            <div style={{ marginTop: '2px' }}>
              <label className="toggle-label">
                <input
                  type="checkbox"
                  className="toggle-checkbox"
                  checked={webBatchMode}
                  onChange={(e) => setWebBatchMode(e.target.checked)}
                />
                <span>Process and save all products in loaded address</span>
              </label>
            </div>

            <button
              className="btn btn-secondary"
              style={{ width: '100%' }}
              onClick={handleModifyLocationWeb}
              disabled={
                !loadedSlot ||
                (!webBatchMode && selectedContentIds.length === 0) ||
                (webBatchMode && loadedContents.length === 0)
              }
            >
              {webBatchMode ? "Modify all products' web location" : "Modify selected product's web location"}
            </button>

            {uploadStatusText && <div className="upload-status-label">{uploadStatusText}</div>}

            <div className="hint-label">{copyStatusText}</div>
          </div>
        </div>
      </div>
    </div>
  );
});
