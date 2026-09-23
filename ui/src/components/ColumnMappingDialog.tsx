import React, { useState, useEffect } from 'react';
import { CSVData, CSVColumnMapping } from '../types';

interface ColumnMappingDialogProps {
  isOpen: boolean;
  csvData: CSVData | null;
  onConfirm: (mapping: CSVColumnMapping) => void;
  onCancel: () => void;
  modeTitle?: string;
}

export const ColumnMappingDialog: React.FC<ColumnMappingDialogProps> = ({
  isOpen,
  csvData,
  onConfirm,
  onCancel,
  modeTitle = 'Import CSV',
}) => {
  const [codeCol, setCodeCol] = useState<string>('');
  const [nameCol, setNameCol] = useState<string>('');
  const [qtyCol, setQtyCol] = useState<string>('');
  const [locCol, setLocCol] = useState<string>('');

  useEffect(() => {
    if (!csvData || csvData.headers.length === 0) return;

    const headers = csvData.headers;
    const normalized = headers.map((h) =>
      h.toLowerCase().replace(/[^a-z0-9]/g, '')
    );

    const findMatch = (candidates: string[], fallbackIdx: number): string => {
      for (const candidate of candidates) {
        const idx = normalized.indexOf(candidate);
        if (idx !== -1) return headers[idx];
      }
      return headers[Math.min(fallbackIdx, headers.length - 1)] || '';
    };

    setCodeCol(
      findMatch(
        ['productid', 'productcode', 'sku', 'itemid', 'itemcode', 'id', 'code', 'mahang', 'masanpham', 'barcode'],
        0
      )
    );

    setNameCol(
      findMatch(
        ['productname', 'itemname', 'name', 'description', 'productdescription', 'tenhang', 'tensanpham'],
        1
      )
    );

    setQtyCol(
      findMatch(
        ['stockqty', 'quantity', 'tonkho', 'soluong', 'onhand', 'soluongton', 'qty'],
        2
      )
    );

    setLocCol(
      findMatch(
        ['location', 'vitri', 'slot', 'bin', 'locid', 'vitrikho'],
        -1
      )
    );
  }, [csvData]);

  if (!isOpen || !csvData) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!codeCol || !nameCol) {
      alert('Please select both Product Code and Product Name columns.');
      return;
    }
    onConfirm({
      code_col: codeCol,
      name_col: nameCol,
      qty_col: qtyCol,
      loc_col: locCol || undefined,
    });
  };

  const previewRows = csvData.rows.slice(0, 5);

  return (
    <div className="modal-backdrop">
      <div className="modal-content" style={{ maxWidth: '680px' }}>
        <div className="modal-header">
          <h3 className="modal-title">{modeTitle} - Match Columns</h3>
          <button className="modal-close" onClick={onCancel}>
            &times;
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '1.25rem' }}>
              <div className="form-group">
                <label className="form-label">Product ID / Barcode *</label>
                <select
                  className="input-select"
                  value={codeCol}
                  onChange={(e) => setCodeCol(e.target.value)}
                  required
                >
                  <option value="">-- Select Column --</option>
                  {csvData.headers.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">Product Name *</label>
                <select
                  className="input-select"
                  value={nameCol}
                  onChange={(e) => setNameCol(e.target.value)}
                  required
                >
                  <option value="">-- Select Column --</option>
                  {csvData.headers.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">Stock Quantity</label>
                <select
                  className="input-select"
                  value={qtyCol}
                  onChange={(e) => setQtyCol(e.target.value)}
                >
                  <option value="">-- Select Column (Optional) --</option>
                  {csvData.headers.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">Location ID</label>
                <select
                  className="input-select"
                  value={locCol}
                  onChange={(e) => setLocCol(e.target.value)}
                >
                  <option value="">-- Select Column (Optional) --</option>
                  {csvData.headers.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.4rem' }}>
              CSV Preview (first 5 of {csvData.rows.length} rows):
            </div>
            <div className="table-container" style={{ maxHeight: '200px' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    {csvData.headers.map((h) => (
                      <th key={h}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {previewRows.map((row, idx) => (
                    <tr key={idx}>
                      {csvData.headers.map((h) => (
                        <td key={h}>{row[h] || ''}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onCancel}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary">
              Confirm & Import
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
