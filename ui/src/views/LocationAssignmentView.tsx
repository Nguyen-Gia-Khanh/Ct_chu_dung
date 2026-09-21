import React, { useState, useEffect, useRef } from 'react';
import { Product, OnHandProduct, SlotAddress, CSVData, CSVColumnMapping, CellContent } from '../types';
import { ApiService } from '../services/api';
import { makeSlotName, parseSlotName, normalizeSearch, formatProductId, getShelfCode } from '../utils/coordinates';
import { StockQuantityDialog, ProductQuantityItem } from '../components/StockQuantityDialog';
import { ColumnMappingDialog } from '../components/ColumnMappingDialog';

export const LocationAssignmentView: React.FC = () => {
  // State
  const [catalog, setCatalog] = useState<Product[]>([]);
  const [pendingQueue, setPendingQueue] = useState<OnHandProduct[]>([]);
  const [onHandBatch, setOnHandBatch] = useState<OnHandProduct[]>([]);
  const [slotContents, setSlotContents] = useState<CellContent[]>([]);

  // Search
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Target Location Address
  const [floor, setFloor] = useState<number>(1);
  const [side, setSide] = useState<number>(1);
  const [shelf, setShelf] = useState<string>('A');
  const [row, setRow] = useState<number>(1);
  const [col, setCol] = useState<number>(1);

  // Options
  const [uploadToKiotViet, setUploadToKiotViet] = useState<boolean>(false);
  const [logs, setLogs] = useState<string[]>([]);

  // Dialogs
  const [stockDialogProducts, setStockDialogProducts] = useState<ProductQuantityItem[] | null>(null);
  const [csvDataToMap, setCsvDataToMap] = useState<{ data: CSVData; mode: 'new' | 'return' } | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const importModeRef = useRef<'new' | 'return'>('new');

  const currentSlotName = makeSlotName(floor, shelf, row, col, side);

  useEffect(() => {
    refreshData();
  }, []);

  useEffect(() => {
    loadSlotContents();
  }, [floor, side, shelf, row, col]);

  const refreshData = async () => {
    const [cats, pends] = await Promise.all([
      ApiService.getCatalog(),
      ApiService.getPendingQueue(),
    ]);
    setCatalog(cats);
    setPendingQueue(pends);
  };

  const loadSlotContents = async () => {
    const shelfCode = getShelfCode(floor, side, shelf);
    const cells = await ApiService.getShelfCells(shelfCode);
    const cell = cells[currentSlotName];
    setSlotContents(cell ? cell.items : []);
  };

  const addLog = (msg: string) => {
    const time = new Date().toLocaleTimeString();
    setLogs((prev) => [`[${time}] ${msg}`, ...prev.slice(0, 40)]);
  };

  // Move queue item to on-hand batch
  const handleQueueToHand = (item: OnHandProduct) => {
    if (!onHandBatch.some((b) => b.code === item.code)) {
      setOnHandBatch((prev) => [...prev, item]);
      addLog(`Added ${item.code} to on-hand batch.`);
    }
  };

  const handleCatalogToHand = (prod: Product) => {
    if (!onHandBatch.some((b) => b.code === prod.product_id)) {
      setOnHandBatch((prev) => [
        ...prev,
        {
          code: prod.product_id,
          name: prod.product_name,
          on_hand: prod.on_hand,
          loc_id: prod.loc_id,
        },
      ]);
      addLog(`Added ${prod.product_id} to on-hand batch.`);
    }
  };

  const handleRemoveFromHand = (code: string) => {
    setOnHandBatch((prev) => prev.filter((b) => b.code !== code));
  };

  // Assign on-hand batch to address
  const handleAssignOnHandToAddress = () => {
    if (onHandBatch.length === 0) {
      alert('On-hand batch is empty. Select products to stage first.');
      return;
    }
    const items = onHandBatch.map((b) => ({
      id: b.code,
      name: b.name,
      initialQuantity: b.on_hand || 1,
    }));
    setStockDialogProducts(items);
  };

  const handleConfirmStockAssignment = async (quantities: Record<string, number>) => {
    const slotObj: SlotAddress = { floor, side, shelf, row, col };
    for (const [prodId, qty] of Object.entries(quantities)) {
      const found =
        catalog.find((c) => c.product_id === prodId) ||
        pendingQueue.find((p) => p.code === prodId) ||
        onHandBatch.find((b) => b.code === prodId);

      const name = found ? ('name' in found ? found.name : found.product_name) : prodId;
      const barcode = found && 'barcode' in found ? found.barcode : prodId;

      const res = await ApiService.assignLocation({
        product_id: prodId,
        product_name: name,
        barcode: barcode,
        slot: slotObj,
        quantity: qty,
        upload_to_kiotviet: uploadToKiotViet,
      });

      if (res.success) {
        addLog(res.message || `Assigned ${prodId} to ${currentSlotName}`);
      } else {
        addLog(res.error || `Failed to assign ${prodId}`);
      }
    }

    setStockDialogProducts(null);
    setOnHandBatch([]);
    await refreshData();
    await loadSlotContents();
  };

  // Direct move from catalog
  const handleDirectMove = async (prod: Product) => {
    const targetSlot: SlotAddress = { floor, side, shelf, row, col };
    const res = await ApiService.directMoveLocation(prod.product_id, targetSlot);
    if (res.success) {
      addLog(`Direct moved ${prod.product_id} to ${currentSlotName}`);
      await refreshData();
      await loadSlotContents();
    } else {
      addLog(res.error || 'Move failed');
    }
  };

  // Move slot product back to on-hand
  const handleSlotProductToHand = (item: CellContent) => {
    handleCatalogToHand({
      product_id: item.product_id,
      product_name: item.product_name,
      barcode: item.barcode,
      on_hand: item.quantity,
      loc_id: currentSlotName,
    });
  };

  const handleRemoveSlotProduct = async (productId: string) => {
    if (confirm(`Remove ${productId} from ${currentSlotName}?`)) {
      await ApiService.removePlacement(productId, currentSlotName);
      addLog(`Removed ${productId} from ${currentSlotName}`);
      await refreshData();
      await loadSlotContents();
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
      addLog(`CSV import successful: ${res.message}`);
      await refreshData();
    } else {
      addLog(`CSV import error: ${res.error}`);
    }
    setCsvDataToMap(null);
  };

  // Filter lists
  const filteredPending = pendingQueue.filter((p) => {
    if (!searchQuery) return true;
    const s = normalizeSearch(searchQuery);
    return (
      normalizeSearch(p.code).includes(s) ||
      normalizeSearch(p.name).includes(s)
    );
  });

  const filteredCatalog = catalog.filter((p) => {
    if (!searchQuery) return true;
    const s = normalizeSearch(searchQuery);
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

      <div className="split-pane three-column">
        {/* PANE 1: Products (Matching Tkinter Products panel) */}
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">Products</span>
            <div style={{ display: 'flex', gap: '0.3rem' }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => handleTriggerCSV('new')}
              >
                Import CSV
              </button>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => handleTriggerCSV('return')}
              >
                Return CSV
              </button>
            </div>
          </div>

          <div className="panel-body">
            <div className="form-group">
              <label className="form-label">Search code, full name, or barcode</label>
              <div className="input-search-wrapper">
                <input
                  type="text"
                  className="input-text"
                  placeholder="Type to filter queue and catalog..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onFocus={(e) => e.target.select()}
                />
                {searchQuery && (
                  <button className="search-clear-btn" onClick={() => setSearchQuery('')}>
                    &times;
                  </button>
                )}
              </div>
            </div>

            {/* Total Unassigned Queue */}
            <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
              <span className="form-label" style={{ fontWeight: 600, marginBottom: '0.2rem' }}>
                Total Unassigned Product Queue ({pendingQueue.length})
              </span>
              <div className="table-container" style={{ flex: 1, maxHeight: '210px' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th style={{ width: '105px' }}>Product ID</th>
                      <th>Product Name</th>
                      <th style={{ width: '50px', textAlign: 'right' }}>Stock</th>
                      <th style={{ width: '60px', textAlign: 'center' }}>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredPending.slice(0, 100).map((item) => (
                      <tr key={item.code} className={item.returned ? 'returned' : ''}>
                        <td className="font-mono">
                          <strong>{item.code}</strong>
                        </td>
                        <td>{item.name}</td>
                        <td style={{ textAlign: 'right' }}>{item.on_hand}</td>
                        <td style={{ textAlign: 'center' }}>
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={() => handleQueueToHand(item)}
                            title="Move to on-hand batch"
                          >
                            + Hand
                          </button>
                        </td>
                      </tr>
                    ))}
                    {filteredPending.length > 100 && (
                      <tr>
                        <td colSpan={4} style={{ textAlign: 'center', color: '#616161', padding: '6px', fontSize: '11px', background: '#f8f8f8' }}>
                          Showing top 100 of {filteredPending.length} items. Refine search to see more.
                        </td>
                      </tr>
                    )}
                    {filteredPending.length === 0 && (
                      <tr>
                        <td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                          No pending products.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Full Product Catalog with Location ID Join */}
            <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
              <span className="form-label" style={{ fontWeight: 600, marginBottom: '0.2rem' }}>
                Full Product Catalog ({catalog.length})
              </span>
              <div className="table-container" style={{ flex: 1, maxHeight: '210px' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th style={{ width: '95px' }}>Product ID</th>
                      <th>Product Name</th>
                      <th style={{ width: '75px' }}>Location</th>
                      <th style={{ width: '110px', textAlign: 'center' }}>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredCatalog.slice(0, 100).map((prod) => (
                      <tr key={prod.product_id}>
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
                        <td style={{ textAlign: 'center' }}>
                          <div style={{ display: 'flex', gap: '0.2rem', justifyContent: 'center' }}>
                            <button
                              className="btn btn-secondary btn-sm"
                              onClick={() => handleCatalogToHand(prod)}
                              title="Stage to on-hand batch"
                            >
                              + Hand
                            </button>
                            <button
                              className="btn btn-primary btn-sm"
                              onClick={() => handleDirectMove(prod)}
                              title={`Direct move to ${currentSlotName}`}
                            >
                              Move
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                    {filteredCatalog.length > 100 && (
                      <tr>
                        <td colSpan={4} style={{ textAlign: 'center', color: '#616161', padding: '6px', fontSize: '11px', background: '#f8f8f8' }}>
                          Showing top 100 of {filteredCatalog.length} items. Refine search to see more.
                        </td>
                      </tr>
                    )}
                    {filteredCatalog.length === 0 && (
                      <tr>
                        <td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                          No catalog items found.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>

        {/* PANE 2: On-Hand Queue and Shelf Address */}
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">On-Hand Queue and Shelf Address</span>
            <span className="loc-pill assigned">{currentSlotName}</span>
          </div>

          <div className="panel-body">
            <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.2rem' }}>
                <span className="form-label" style={{ fontWeight: 600 }}>
                  On-Hand Working Batch ({onHandBatch.length})
                </span>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => setOnHandBatch([])}
                  disabled={onHandBatch.length === 0}
                >
                  Clear on-hand
                </button>
              </div>

              <div className="table-container" style={{ flex: 1, maxHeight: '210px' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th style={{ width: '105px' }}>Product ID</th>
                      <th>Product Name</th>
                      <th style={{ width: '45px', textAlign: 'right' }}>Qty</th>
                      <th style={{ width: '45px', textAlign: 'center' }}>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {onHandBatch.map((item) => (
                      <tr key={item.code}>
                        <td className="font-mono">
                          <strong>{item.code}</strong>
                        </td>
                        <td>{item.name}</td>
                        <td style={{ textAlign: 'right' }}>{item.on_hand}</td>
                        <td style={{ textAlign: 'center' }}>
                          <button
                            className="btn btn-danger btn-sm"
                            onClick={() => handleRemoveFromHand(item.code)}
                            title="Remove from batch"
                          >
                            &times;
                          </button>
                        </td>
                      </tr>
                    ))}
                    {onHandBatch.length === 0 && (
                      <tr>
                        <td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                          On-hand batch is empty. Add products from the left.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Target Address Card */}
            <div style={{ background: 'var(--vscode-workbench-bg)', border: '1px solid var(--vscode-border)', borderRadius: '3px', padding: '8px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="form-label" style={{ fontWeight: 700 }}>
                  Target Shelf Address
                </span>
                <span className="loc-pill assigned">{currentSlotName}</span>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '4px' }}>
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
                  <select className="input-select" value={side} onChange={(e) => setSide(parseInt(e.target.value, 10) || 1)}>
                    <option value={1}>1</option>
                    <option value={2}>2</option>
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

                <div className="form-group">
                  <label className="form-label">Row</label>
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
                  <label className="form-label">Col</label>
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

              <button
                className="btn btn-primary"
                style={{ width: '100%', height: '28px', marginTop: '2px', fontWeight: 600 }}
                onClick={handleAssignOnHandToAddress}
                disabled={onHandBatch.length === 0}
              >
                Assign on-hand → {currentSlotName}
              </button>

              <label className="toggle-label" style={{ marginTop: '2px' }}>
                <input
                  type="checkbox"
                  className="toggle-checkbox"
                  checked={uploadToKiotViet}
                  onChange={(e) => setUploadToKiotViet(e.target.checked)}
                />
                <span>Upload to KiotViet automatically</span>
              </label>
            </div>
          </div>
        </div>

        {/* PANE 3: Loaded Address Contents (Matching Tkinter) */}
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">Loaded Address Contents</span>
            <span style={{ fontSize: '11.5px', color: 'var(--text-secondary)' }}>
              {slotContents.length} item(s)
            </span>
          </div>

          <div className="panel-body">
            <div style={{ fontSize: '11.5px', color: 'var(--text-secondary)' }}>
              Current products stored at <strong className="font-mono">{currentSlotName}</strong>:
            </div>

            <div className="table-container" style={{ flex: 1, maxHeight: '260px' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Product ID</th>
                    <th>Product Name</th>
                    <th style={{ width: '55px' }}>Qty</th>
                    <th style={{ width: '85px' }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {slotContents.map((it) => (
                    <tr key={it.product_id}>
                      <td className="font-mono">
                        <strong>{it.product_id}</strong>
                      </td>
                      <td>{it.product_name}</td>
                      <td>{it.quantity}</td>
                      <td>
                        <div style={{ display: 'flex', gap: '0.2rem' }}>
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={() => handleSlotProductToHand(it)}
                            title="Move product to on-hand"
                          >
                            + Hand
                          </button>
                          <button
                            className="btn btn-danger btn-sm"
                            onClick={() => handleRemoveSlotProduct(it.product_id)}
                            title="Remove product from slot"
                          >
                            Del
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {slotContents.length === 0 && (
                    <tr>
                      <td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                        Slot {currentSlotName} is empty.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              <span className="form-label" style={{ fontWeight: 600 }}>
                Activity Log
              </span>
              <div className="status-log">
                {logs.map((log, i) => (
                  <div key={i}>{log}</div>
                ))}
                {logs.length === 0 && <div>Ready.</div>}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Stock Quantity Dialog */}
      {stockDialogProducts && (
        <StockQuantityDialog
          isOpen={true}
          slotName={currentSlotName}
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
