import React, { useState, useEffect, useRef } from 'react';
import { Product, OnHandProduct, SlotAddress, CSVData, CSVColumnMapping } from '../types';
import { ApiService } from '../services/api';
import { makeSlotName, parseSlotName, normalizeSearch, formatProductId } from '../utils/coordinates';
import { StockQuantityDialog, ProductQuantityItem } from '../components/StockQuantityDialog';
import { ColumnMappingDialog } from '../components/ColumnMappingDialog';

export const LocationAssignmentView: React.FC = () => {
  // State
  const [catalog, setCatalog] = useState<Product[]>([]);
  const [pendingQueue, setPendingQueue] = useState<OnHandProduct[]>([]);
  const [batchQueue, setBatchQueue] = useState<OnHandProduct[]>([]);
  const [activeListTab, setActiveListTab] = useState<'pending' | 'catalog' | 'batch'>('pending');

  // Search
  const [catalogSearch, setCatalogSearch] = useState<string>('');
  const [queueSearch, setQueueSearch] = useState<string>('');

  // Target Location Address
  const [floor, setFloor] = useState<number>(1);
  const [side, setSide] = useState<number>(1);
  const [shelf, setShelf] = useState<string>('A');
  const [row, setRow] = useState<number>(1);
  const [col, setCol] = useState<number>(1);
  const [manualLocInput, setManualLocInput] = useState<string>('');

  // Options
  const [uploadToKiotViet, setUploadToKiotViet] = useState<boolean>(false);
  const [logs, setLogs] = useState<string[]>([]);

  // Dialogs
  const [stockDialogProducts, setStockDialogProducts] = useState<ProductQuantityItem[] | null>(null);
  const [csvDataToMap, setCsvDataToMap] = useState<{ data: CSVData; mode: 'new' | 'return' } | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const importModeRef = useRef<'new' | 'return'>('new');

  useEffect(() => {
    refreshData();
  }, []);

  const refreshData = async () => {
    const [cats, pends] = await Promise.all([
      ApiService.getCatalog(),
      ApiService.getPendingQueue(),
    ]);
    setCatalog(cats);
    setPendingQueue(pends);
  };

  const addLog = (msg: string, type: 'info' | 'success' | 'error' = 'info') => {
    const time = new Date().toLocaleTimeString();
    setLogs((prev) => [`[${time}] ${msg}`, ...prev.slice(0, 50)]);
  };

  // Sync target slot from manual input if changed
  const handleManualLocChange = (val: string) => {
    setManualLocInput(val);
    const parsed = parseSlotName(val);
    if (parsed) {
      setFloor(parsed.floor);
      setSide(parsed.side);
      setShelf(parsed.shelf);
      setRow(parsed.row);
      setCol(parsed.col);
    }
  };

  const currentComputedSlot = makeSlotName(floor, shelf, row, col, side);

  // Add to batch queue
  const handleAddToBatch = (item: OnHandProduct) => {
    if (!batchQueue.some((b) => b.code === item.code)) {
      setBatchQueue((prev) => [...prev, item]);
      addLog(`Added ${item.code} to work batch.`, 'info');
    }
  };

  const handleRemoveFromBatch = (code: string) => {
    setBatchQueue((prev) => prev.filter((b) => b.code !== code));
  };

  // Assign action
  const handleStartAssign = () => {
    let itemsToAssign: ProductQuantityItem[] = [];

    if (activeListTab === 'batch') {
      itemsToAssign = batchQueue.map((b) => ({
        id: b.code,
        name: b.name,
        initialQuantity: b.on_hand || 1,
      }));
    } else if (activeListTab === 'pending') {
      const selected = pendingQueue.filter((p) => p.selected);
      if (selected.length > 0) {
        itemsToAssign = selected.map((p) => ({
          id: p.code,
          name: p.name,
          initialQuantity: p.on_hand || 1,
        }));
      }
    }

    if (itemsToAssign.length === 0) {
      alert('Please select at least one product to assign.');
      return;
    }

    setStockDialogProducts(itemsToAssign);
  };

  const handleConfirmStockAssignment = async (quantities: Record<string, number>) => {
    const slotObj: SlotAddress = { floor, side, shelf, row, col };
    for (const [prodId, qty] of Object.entries(quantities)) {
      const found = catalog.find((c) => c.product_id === prodId) || pendingQueue.find((p) => p.code === prodId);
      const res = await ApiService.assignLocation({
        product_id: prodId,
        product_name: found ? ('name' in found ? found.name : found.product_name) : prodId,
        barcode: found && 'barcode' in found ? found.barcode : prodId,
        slot: slotObj,
        quantity: qty,
        upload_to_kiotviet: uploadToKiotViet,
      });

      if (res.success) {
        addLog(res.message || `Assigned ${prodId} to ${currentComputedSlot}`, 'success');
      } else {
        addLog(res.error || `Failed to assign ${prodId}`, 'error');
      }
    }

    setStockDialogProducts(null);
    setBatchQueue([]);
    refreshData();
  };

  // Direct move for catalog item
  const handleDirectMove = async (prod: Product) => {
    const targetSlot: SlotAddress = { floor, side, shelf, row, col };
    const res = await ApiService.directMoveLocation(prod.product_id, targetSlot);
    if (res.success) {
      addLog(`Direct moved ${prod.product_id} to ${currentComputedSlot}`, 'success');
      refreshData();
    } else {
      addLog(res.error || 'Move failed', 'error');
    }
  };

  // CSV Import handling
  const handleTriggerCSV = (mode: 'new' | 'return') => {
    importModeRef.current = mode;
    fileInputRef.current?.click();
  };

  const handleFileSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const text = event.target?.result as string;
      const lines = text.split(/\r\n|\n/).filter((l) => l.trim().length > 0);
      if (lines.length === 0) return;

      const headers = lines[0].split(',').map((h) => h.trim().replace(/^"|"$/g, ''));
      const rows: Record<string, string>[] = [];

      for (let i = 1; i < lines.length; i++) {
        const parts = lines[i].split(',').map((p) => p.trim().replace(/^"|"$/g, ''));
        const rowObj: Record<string, string> = {};
        headers.forEach((h, idx) => {
          rowObj[h] = parts[idx] || '';
        });
        rows.push(rowObj);
      }

      setCsvDataToMap({
        data: { headers, rows },
        mode: importModeRef.current,
      });
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  const handleConfirmCSVMapping = async (mapping: CSVColumnMapping) => {
    if (!csvDataToMap) return;
    const res = await ApiService.importCSV(csvDataToMap.data, mapping, csvDataToMap.mode);
    if (res.success) {
      addLog(`CSV Import successful: ${res.message}`, 'success');
      refreshData();
    } else {
      addLog(`CSV Import error: ${res.error}`, 'error');
    }
    setCsvDataToMap(null);
  };

  // Filters
  const filteredPending = pendingQueue.filter((p) => {
    if (!queueSearch) return true;
    const s = normalizeSearch(queueSearch);
    return (
      normalizeSearch(p.code).includes(s) ||
      normalizeSearch(p.name).includes(s) ||
      (p.loc_id && normalizeSearch(p.loc_id).includes(s))
    );
  });

  const filteredCatalog = catalog.filter((p) => {
    if (!catalogSearch) return true;
    const s = normalizeSearch(catalogSearch);
    return (
      normalizeSearch(p.product_id).includes(s) ||
      normalizeSearch(p.barcode).includes(s) ||
      normalizeSearch(p.product_name).includes(s) ||
      (p.loc_id && normalizeSearch(p.loc_id).includes(s))
    );
  });

  return (
    <div className="view-container">
      <input
        type="file"
        ref={fileInputRef}
        accept=".csv"
        style={{ display: 'none' }}
        onChange={handleFileSelected}
      />

      <div className="split-pane left-heavy">
        {/* Left Side: Product Queues & Catalog */}
        <div className="panel">
          <div className="panel-header">
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button
                className={`btn btn-sm ${activeListTab === 'pending' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setActiveListTab('pending')}
              >
                Pending Queue ({pendingQueue.length})
              </button>
              <button
                className={`btn btn-sm ${activeListTab === 'catalog' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setActiveListTab('catalog')}
              >
                Full Catalog ({catalog.length})
              </button>
              <button
                className={`btn btn-sm ${activeListTab === 'batch' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setActiveListTab('batch')}
              >
                Work Batch ({batchQueue.length})
              </button>
            </div>

            <div style={{ display: 'flex', gap: '0.4rem' }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => handleTriggerCSV('new')}
                title="Import new products from CSV"
              >
                📥 Import CSV
              </button>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => handleTriggerCSV('return')}
                title="Import returned inventory from CSV"
              >
                ↩️ Return CSV
              </button>
            </div>
          </div>

          <div className="panel-body">
            {/* Tab: Pending Queue */}
            {activeListTab === 'pending' && (
              <div>
                <div className="input-search-wrapper" style={{ marginBottom: '0.75rem' }}>
                  <input
                    type="text"
                    className="input-text"
                    placeholder="Search pending queue by code or name..."
                    value={queueSearch}
                    onChange={(e) => setQueueSearch(e.target.value)}
                    onFocus={(e) => e.target.select()}
                  />
                  {queueSearch && (
                    <button className="search-clear-btn" onClick={() => setQueueSearch('')}>
                      &times;
                    </button>
                  )}
                </div>

                <div className="table-container" style={{ maxHeight: '420px' }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th style={{ width: '36px' }}>
                          <input
                            type="checkbox"
                            onChange={(e) => {
                              const checked = e.target.checked;
                              setPendingQueue((prev) =>
                                prev.map((p) => ({ ...p, selected: checked }))
                              );
                            }}
                          />
                        </th>
                        <th>Product ID</th>
                        <th>Product Name</th>
                        <th>On Hand</th>
                        <th>Current Loc</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredPending.map((item) => (
                        <tr key={item.code} className={item.selected ? 'selected' : ''}>
                          <td>
                            <input
                              type="checkbox"
                              checked={!!item.selected}
                              onChange={(e) => {
                                const checked = e.target.checked;
                                setPendingQueue((prev) =>
                                  prev.map((p) =>
                                    p.code === item.code ? { ...p, selected: checked } : p
                                  )
                                );
                              }}
                            />
                          </td>
                          <td className="font-mono">
                            <strong>{item.code}</strong>
                          </td>
                          <td>{item.name}</td>
                          <td>{item.on_hand}</td>
                          <td>
                            {item.loc_id ? (
                              <span className="loc-pill assigned">{item.loc_id}</span>
                            ) : (
                              <span className="loc-pill">Unassigned</span>
                            )}
                          </td>
                          <td>
                            <button
                              className="btn btn-secondary btn-sm"
                              onClick={() => handleAddToBatch(item)}
                            >
                              + Batch
                            </button>
                          </td>
                        </tr>
                      ))}
                      {filteredPending.length === 0 && (
                        <tr>
                          <td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                            No pending products in queue.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Tab: Full Catalog with Location ID join */}
            {activeListTab === 'catalog' && (
              <div>
                <div className="input-search-wrapper" style={{ marginBottom: '0.75rem' }}>
                  <input
                    type="text"
                    className="input-text"
                    placeholder="Search catalog by code, name, barcode, location..."
                    value={catalogSearch}
                    onChange={(e) => setCatalogSearch(e.target.value)}
                    onFocus={(e) => e.target.select()}
                  />
                  {catalogSearch && (
                    <button className="search-clear-btn" onClick={() => setCatalogSearch('')}>
                      &times;
                    </button>
                  )}
                </div>

                <div className="table-container" style={{ maxHeight: '420px' }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Product ID</th>
                        <th>Product Name</th>
                        <th>On Hand</th>
                        <th>Location ID</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredCatalog.map((prod) => (
                        <tr key={prod.product_id}>
                          <td className="font-mono">
                            <strong>{prod.product_id}</strong>
                          </td>
                          <td>{prod.product_name}</td>
                          <td>{prod.on_hand}</td>
                          <td>
                            {prod.loc_id ? (
                              <span className="loc-pill assigned">{prod.loc_id}</span>
                            ) : (
                              <span className="loc-pill">None</span>
                            )}
                          </td>
                          <td>
                            <div style={{ display: 'flex', gap: '0.3rem' }}>
                              <button
                                className="btn btn-secondary btn-sm"
                                onClick={() =>
                                  handleAddToBatch({
                                    code: prod.product_id,
                                    name: prod.product_name,
                                    on_hand: prod.on_hand,
                                    loc_id: prod.loc_id,
                                  })
                                }
                              >
                                + Batch
                              </button>
                              <button
                                className="btn btn-primary btn-sm"
                                onClick={() => handleDirectMove(prod)}
                                title={`Move directly to ${currentComputedSlot}`}
                              >
                                ➔ Move Here
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Tab: Work Batch Queue */}
            {activeListTab === 'batch' && (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
                  <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                    Items to be assigned to <strong>{currentComputedSlot}</strong>
                  </span>
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => setBatchQueue([])}
                    disabled={batchQueue.length === 0}
                  >
                    Clear Batch
                  </button>
                </div>

                <div className="table-container" style={{ maxHeight: '420px' }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Code</th>
                        <th>Name</th>
                        <th>Qty</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {batchQueue.map((item) => (
                        <tr key={item.code}>
                          <td className="font-mono">
                            <strong>{item.code}</strong>
                          </td>
                          <td>{item.name}</td>
                          <td>{item.on_hand}</td>
                          <td>
                            <button
                              className="btn btn-danger btn-sm"
                              onClick={() => handleRemoveFromBatch(item.code)}
                            >
                              Remove
                            </button>
                          </td>
                        </tr>
                      ))}
                      {batchQueue.length === 0 && (
                        <tr>
                          <td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                            Batch is empty. Select items from Pending or Catalog.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right Side: Target Address & Execution */}
        <div className="panel">
          <div className="panel-header">
            <h2 className="panel-title">📍 Target Shelf Address</h2>
            <span className="loc-pill assigned" style={{ fontSize: '0.9rem' }}>
              {currentComputedSlot}
            </span>
          </div>

          <div className="panel-body">
            <div className="form-group" style={{ marginBottom: '1.25rem' }}>
              <label className="form-label">Quick Jump / Manual Location Input</label>
              <input
                type="text"
                className="input-text font-mono"
                placeholder="e.g. L1-1A8-10"
                value={manualLocInput}
                onChange={(e) => handleManualLocChange(e.target.value.toUpperCase())}
              />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem', marginBottom: '1rem' }}>
              <div className="form-group">
                <label className="form-label">Floor</label>
                <input
                  type="number"
                  min="1"
                  max="10"
                  className="input-text font-mono"
                  value={floor}
                  onChange={(e) => setFloor(parseInt(e.target.value, 10) || 1)}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Side</label>
                <select
                  className="input-select"
                  value={side}
                  onChange={(e) => setSide(parseInt(e.target.value, 10) || 1)}
                >
                  <option value={1}>Side 1</option>
                  <option value={2}>Side 2</option>
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">Shelf</label>
                <input
                  type="text"
                  maxLength={3}
                  className="input-text font-mono"
                  value={shelf}
                  onChange={(e) => setShelf(e.target.value.toUpperCase())}
                />
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '1.25rem' }}>
              <div className="form-group">
                <label className="form-label">Row (From Ground Up)</label>
                <input
                  type="number"
                  min="1"
                  max="25"
                  className="input-text font-mono"
                  value={row}
                  onChange={(e) => setRow(parseInt(e.target.value, 10) || 1)}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Column / Slot</label>
                <input
                  type="number"
                  min="1"
                  max="50"
                  className="input-text font-mono"
                  value={col}
                  onChange={(e) => setCol(parseInt(e.target.value, 10) || 1)}
                />
              </div>
            </div>

            <div style={{ marginBottom: '1.25rem' }}>
              <label className="toggle-label">
                <input
                  type="checkbox"
                  className="toggle-checkbox"
                  checked={uploadToKiotViet}
                  onChange={(e) => setUploadToKiotViet(e.target.checked)}
                />
                <span>🌐 Upload / Sync to KiotViet Web Automatically</span>
              </label>
            </div>

            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.25rem' }}>
              <button
                className="btn btn-primary"
                style={{ flex: 1, padding: '0.65rem' }}
                onClick={handleStartAssign}
              >
                ✅ Assign Selected to {currentComputedSlot}
              </button>
            </div>

            {/* Status log */}
            <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.4rem' }}>
              Activity Log:
            </div>
            <div className="status-log">
              {logs.map((log, i) => (
                <div key={i}>{log}</div>
              ))}
              {logs.length === 0 && <div>Waiting for action...</div>}
            </div>
          </div>
        </div>
      </div>

      {/* Stock Quantity Dialog */}
      {stockDialogProducts && (
        <StockQuantityDialog
          isOpen={true}
          slotName={currentComputedSlot}
          products={stockDialogProducts}
          onConfirm={handleConfirmStockAssignment}
          onCancel={() => setStockDialogProducts(null)}
        />
      )}

      {/* CSV Column Mapping Dialog */}
      {csvDataToMap && (
        <ColumnMappingDialog
          isOpen={true}
          csvData={csvDataToMap.data}
          modeTitle={csvDataToMap.mode === 'new' ? 'Import New Products' : 'Import Returned Stock'}
          onConfirm={handleConfirmCSVMapping}
          onCancel={() => setCsvDataToMap(null)}
        />
      )}
    </div>
  );
};
