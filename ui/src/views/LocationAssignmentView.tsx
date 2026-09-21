import React, { useState, useEffect } from 'react';
import { Product, ApiResponse } from '../types';
import { ApiService } from '../services/api';
import { normalizeSearch } from '../utils/coordinates';

interface QueueItem {
  code: string;
  name: string;
  on_hand: number;
  returned?: boolean;
}

interface OnHandItem {
  product_id: string;
  product_name: string;
  stock_qty: number;
}

interface SlotInfo {
  slot_id: number;
  floor: number;
  side: number;
  shelf: string;
  row: number;
  col: number;
  slot_name: string;
}

interface LoadedSlotContent {
  product_id: string;
  product_name: string;
  stock_qty: number;
  assigned_at: string;
}

export const LocationAssignmentView: React.FC = () => {
  // Data State
  const [catalog, setCatalog] = useState<Product[]>([]);
  const [pendingQueue, setPendingQueue] = useState<QueueItem[]>([]);
  const [onHandProducts, setOnHandProducts] = useState<OnHandItem[]>([]);

  // Selection states (multi-select arrays of IDs)
  const [selectedQueueIds, setSelectedQueueIds] = useState<string[]>([]);
  const [selectedCatalogIds, setSelectedCatalogIds] = useState<string[]>([]);
  const [selectedOnHandIds, setSelectedOnHandIds] = useState<string[]>([]);
  const [selectedContentIds, setSelectedContentIds] = useState<string[]>([]);

  // Search & dynamic location indicator
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [searchLocationText, setSearchLocationText] = useState<string>('');

  // Target Location Inputs (default 1-1-A-1-1)
  const [floor, setFloor] = useState<string | number>(1);
  const [side, setSide] = useState<string | number>(1);
  const [shelf, setShelf] = useState<string>('A');
  const [row, setRow] = useState<number>(1);
  const [col, setCol] = useState<number>(1);

  // Loaded slot state
  const [loadedSlot, setLoadedSlot] = useState<SlotInfo | null>(null);
  const [loadedContents, setLoadedContents] = useState<LoadedSlotContent[]>([]);
  const [addressStatusText, setAddressStatusText] = useState<string>('Enter an existing shelf address and load it.');

  // Web options
  const [webBatchMode, setWebBatchMode] = useState<boolean>(false);
  const [uploadStatusText, setUploadStatusText] = useState<string>('');
  const [copyStatusText, setCopyStatusText] = useState<string>('Double-click a row to copy its Product ID.');

  useEffect(() => {
    refreshData();
    handleLoadAddressDirect('1', '1', 'A', 1, 1);
  }, []);

  const refreshData = async () => {
    const [cats, pends, hands] = await Promise.all([
      ApiService.getCatalog(),
      ApiService.getPendingQueue() as unknown as Promise<QueueItem[]>,
      ApiService.getOnHandProducts() as unknown as Promise<OnHandItem[]>,
    ]);
    setCatalog(cats);
    setPendingQueue(pends || []);
    setOnHandProducts(hands || []);
  };

  // Live location check based on search query matching Tkinter logic
  useEffect(() => {
    const q = searchQuery.trim();
    if (!q) {
      setSearchLocationText('');
      return;
    }
    const term = normalizeSearch(q);
    const inHand = onHandProducts.find(
      (h) => normalizeSearch(h.product_id) === term || normalizeSearch(h.product_id.replace(/-/g, '')) === term.replace(/-/g, '')
    );
    if (inHand) {
      setSearchLocationText(`In on-hand queue · stock ${inHand.stock_qty != null ? inHand.stock_qty : 'Unknown'}`);
      return;
    }
    const inCat = catalog.find(
      (c) => normalizeSearch(c.product_id) === term || normalizeSearch(c.product_id.replace(/-/g, '')) === term.replace(/-/g, '')
    );
    if (inCat && inCat.loc_id) {
      setSearchLocationText(`Already at ${inCat.loc_id}`);
      return;
    }
    const inPend = pendingQueue.find(
      (p) => normalizeSearch(p.code) === term || normalizeSearch(p.code.replace(/-/g, '')) === term.replace(/-/g, '')
    );
    if (inPend && inPend.returned) {
      setSearchLocationText(`In total queue · returned stock ${inPend.on_hand != null ? inPend.on_hand : 'Unknown'}`);
      return;
    }
    if (inCat && !inCat.loc_id) {
      setSearchLocationText('Not assigned to any location.');
      return;
    }
    setSearchLocationText('');
  }, [searchQuery, catalog, pendingQueue, onHandProducts]);

  const handleToggleSelect = (
    selectedList: string[],
    setSelectedList: React.Dispatch<React.SetStateAction<string[]>>,
    id: string,
    e?: React.MouseEvent
  ) => {
    if (e && (e.ctrlKey || e.metaKey || e.shiftKey)) {
      setSelectedList((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
    } else {
      setSelectedList((prev) => (prev.length === 1 && prev[0] === id ? [] : [id]));
    }
  };

  const handleMoveSelectedToOnHand = async () => {
    if (selectedQueueIds.length === 0) return;
    const res = await ApiService.addToOnHand(selectedQueueIds);
    if (res.success) {
      setSelectedQueueIds([]);
      await refreshData();
    }
  };

  const handleTransferSelectedToQueue = async () => {
    if (selectedCatalogIds.length === 0) return;
    const res = await ApiService.transferCatalogToQueue(selectedCatalogIds);
    if (res.success) {
      setSelectedCatalogIds([]);
      await refreshData();
    }
  };

  const handleCatalogDoubleClick = (productId: string) => {
    setSearchQuery(productId);
  };

  const handleEditSelectedQuantity = async () => {
    if (selectedOnHandIds.length !== 1) return;
    const pid = selectedOnHandIds[0];
    const item = onHandProducts.find((p) => p.product_id === pid);
    const curr = item && item.stock_qty != null ? item.stock_qty : 1;
    const val = window.prompt(`Product: ${pid}\nCurrent stock: ${curr}\n\nEnter the new whole-number quantity:`, String(curr));
    if (val === null) return;
    const newQty = parseInt(val, 10);
    if (!isNaN(newQty) && newQty >= 0) {
      await ApiService.updateOnHandStock(pid, newQty);
      await refreshData();
    }
  };

  const handleDequeueOnHand = async () => {
    if (selectedOnHandIds.length === 0) return;
    const res = await ApiService.dequeueOnHand(selectedOnHandIds);
    if (res.success) {
      setSelectedOnHandIds([]);
      await refreshData();
    }
  };

  const handleLoadAddressDirect = async (
    f: string | number,
    s: string | number,
    sh: string,
    r: string | number,
    c: string | number
  ) => {
    const res = await ApiService.getSlotAddress(f, s, sh, r, c) as ApiResponse & {
      slot?: SlotInfo;
      contents?: LoadedSlotContent[];
    };
    if (res.success && res.slot) {
      setLoadedSlot(res.slot);
      setLoadedContents(res.contents || []);
      setAddressStatusText(res.message || `Loaded ${res.slot.slot_name}`);
    } else {
      setLoadedSlot(null);
      setLoadedContents([]);
      setAddressStatusText(res.message || `No saved cell at Floor ${f} / Side ${s} / Shelf ${sh} / Row ${r} / Cell ${c}.`);
    }
  };

  const handleLoadAddress = async () => {
    await handleLoadAddressDirect(floor, side, shelf, row, col);
  };

  const handleAssignAddress = async () => {
    if (!loadedSlot) {
      alert('Enter the shelf address and press Load address first.');
      return;
    }
    const pids = selectedOnHandIds.length > 0 ? selectedOnHandIds : onHandProducts.map((p) => p.product_id);
    if (pids.length === 0) {
      alert('Select one or more on-hand products with click first.');
      return;
    }
    const res = await ApiService.assignOnHandToSlot(loadedSlot.slot_id, pids);
    if (res.success) {
      setSelectedOnHandIds([]);
      await refreshData();
      await handleLoadAddressDirect(loadedSlot.floor, loadedSlot.side, loadedSlot.shelf, loadedSlot.row, loadedSlot.col);
    } else {
      alert(res.error || 'Assignment failed');
    }
  };

  const handleCopyProductId = (productId: string) => {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(productId);
      setCopyStatusText(`Copied ${productId} to clipboard.`);
    }
  };

  const handleModifyLoadedStock = async () => {
    if (selectedContentIds.length !== 1 || !loadedSlot) return;
    const pid = selectedContentIds[0];
    const item = loadedContents.find((p) => p.product_id === pid);
    const curr = item && item.stock_qty != null ? item.stock_qty : 1;
    const val = window.prompt(
      `Product: ${pid}\nLocation: ${loadedSlot.slot_name}\nCurrent stock: ${curr}\n\nEnter the new whole-number quantity:`,
      String(curr)
    );
    if (val === null) return;
    const newQty = parseInt(val, 10);
    if (!isNaN(newQty) && newQty >= 0) {
      await ApiService.updateSlotStock(loadedSlot.slot_id, pid, newQty);
      await handleLoadAddressDirect(loadedSlot.floor, loadedSlot.side, loadedSlot.shelf, loadedSlot.row, loadedSlot.col);
    }
  };

  const handleSelectedToHand = async () => {
    if (!loadedSlot || selectedContentIds.length === 0) return;
    const res = await ApiService.moveSlotToOnHand(loadedSlot.slot_id, selectedContentIds);
    if (res.success) {
      setSelectedContentIds([]);
      await refreshData();
      await handleLoadAddressDirect(loadedSlot.floor, loadedSlot.side, loadedSlot.shelf, loadedSlot.row, loadedSlot.col);
    }
  };

  const handleShelfAllToHand = async () => {
    if (!loadedSlot || loadedContents.length === 0) return;
    if (!window.confirm(`Move all ${loadedContents.length} product(s) from ${loadedSlot.slot_name} to on-hand?`)) return;
    const res = await ApiService.moveSlotToOnHand(loadedSlot.slot_id);
    if (res.success) {
      setSelectedContentIds([]);
      await refreshData();
      await handleLoadAddressDirect(loadedSlot.floor, loadedSlot.side, loadedSlot.shelf, loadedSlot.row, loadedSlot.col);
    }
  };

  const handleModifyLocationWeb = async () => {
    if (!loadedSlot) return;
    const targetPids = webBatchMode ? loadedContents.map((c) => c.product_id) : selectedContentIds;
    if (targetPids.length === 0) return;
    const res = await ApiService.modifyLocationWeb(targetPids, loadedSlot.slot_name);
    setUploadStatusText(res.message || 'Updated web location.');
  };

  const handleConnectChrome = async () => {
    const res = await ApiService.connectChrome();
    setUploadStatusText(res.message || 'Chrome connection initiated.');
  };

  const filteredPending = pendingQueue.filter((p) => {
    if (!searchQuery) return true;
    const s = normalizeSearch(searchQuery);
    return normalizeSearch(p.code).includes(s) || normalizeSearch(p.name).includes(s);
  });

  const filteredCatalog = catalog.filter((p) => {
    if (!searchQuery) return true;
    const s = normalizeSearch(searchQuery);
    return (
      normalizeSearch(p.product_id).includes(s) ||
      normalizeSearch(p.barcode).includes(s) ||
      normalizeSearch(p.product_name).includes(s) ||
      (p.loc_id ? normalizeSearch(p.loc_id).includes(s) : false)
    );
  });

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
                    {filteredPending.slice(0, 100).map((item) => (
                      <tr
                        key={item.code}
                        className={`${selectedQueueIds.includes(item.code) ? 'selected-row' : ''} ${
                          item.returned ? 'returned-row' : ''
                        }`}
                        onClick={(e) => handleToggleSelect(selectedQueueIds, setSelectedQueueIds, item.code, e)}
                      >
                        <td className="font-mono">
                          <strong>{item.code}</strong>
                        </td>
                        <td>{item.name}</td>
                        <td style={{ textAlign: 'right' }}>{item.on_hand}</td>
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
                    {filteredCatalog.slice(0, 100).map((prod) => (
                      <tr
                        key={prod.product_id}
                        className={selectedCatalogIds.includes(prod.product_id) ? 'selected-row' : ''}
                        onClick={(e) => handleToggleSelect(selectedCatalogIds, setSelectedCatalogIds, prod.product_id, e)}
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
                      onClick={(e) => handleToggleSelect(selectedOnHandIds, setSelectedOnHandIds, item.product_id, e)}
                    >
                      <td className="font-mono">
                        <strong>{item.product_id}</strong>
                      </td>
                      <td>{item.product_name}</td>
                      <td style={{ textAlign: 'right' }}>{item.stock_qty}</td>
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
                      onClick={(e) => handleToggleSelect(selectedContentIds, setSelectedContentIds, it.product_id, e)}
                      onDoubleClick={() => handleCopyProductId(it.product_id)}
                      title="Double-click to copy Product ID"
                    >
                      <td className="font-mono">
                        <strong>{it.product_id}</strong>
                      </td>
                      <td>{it.product_name}</td>
                      <td style={{ textAlign: 'right' }}>{it.stock_qty}</td>
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
};
