import React, { useState } from 'react';

export interface ProductQuantityItem {
  id: string;
  name: string;
  initialQuantity: number;
}

interface StockQuantityDialogProps {
  isOpen: boolean;
  slotName: string;
  products: ProductQuantityItem[];
  onConfirm: (quantities: Record<string, number>) => void;
  onCancel: () => void;
  title?: string;
  destinationLabel?: string;
  buttonText?: string;
}

export const StockQuantityDialog: React.FC<StockQuantityDialogProps> = ({
  isOpen,
  slotName,
  products,
  onConfirm,
  onCancel,
  title,
  destinationLabel,
  buttonText = 'Assign products',
}) => {
  const [quantities, setQuantities] = useState<Record<string, number>>(() => {
    const init: Record<string, number> = {};
    products.forEach((p) => {
      init[p.id] = p.initialQuantity || 1;
    });
    return init;
  });

  if (!isOpen) return null;

  const handleQtyChange = (productId: string, val: string) => {
    const parsed = parseInt(val, 10);
    setQuantities((prev) => ({
      ...prev,
      [productId]: isNaN(parsed) || parsed < 0 ? 0 : parsed,
    }));
  };

  const handlePreset = (productId: string, delta: number) => {
    setQuantities((prev) => ({
      ...prev,
      [productId]: Math.max(0, (prev[productId] || 0) + delta),
    }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onConfirm(quantities);
  };

  return (
    <div className="modal-backdrop">
      <div className="modal-content" style={{ maxWidth: '640px' }}>
        <div className="modal-header">
          <h3 className="modal-title">{title || `Assign products to ${slotName}`}</h3>
          <button className="modal-close" onClick={onCancel}>
            &times;
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div style={{ marginBottom: '1rem' }}>
              <div style={{ fontSize: '0.9rem', fontWeight: 600 }}>
                {destinationLabel || `Destination: ${slotName}`}
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Enter each product's stock quantity (whole units, 0 or more).
              </div>
            </div>

            <div className="table-container" style={{ maxHeight: '300px' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Product ID</th>
                    <th>Product Name</th>
                    <th style={{ width: '150px' }}>Stock Qty</th>
                  </tr>
                </thead>
                <tbody>
                  {products.map((p) => (
                    <tr key={p.id}>
                      <td className="font-mono">
                        <strong>{p.id}</strong>
                      </td>
                      <td>{p.name}</td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                          <input
                            type="number"
                            min="0"
                            className="input-text font-mono"
                            style={{ width: '65px', padding: '0.25rem 0.4rem' }}
                            value={quantities[p.id] ?? 1}
                            onChange={(e) => handleQtyChange(p.id, e.target.value)}
                          />
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            onClick={() => handlePreset(p.id, 1)}
                            title="Add 1"
                          >
                            +1
                          </button>
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            onClick={() => handlePreset(p.id, 5)}
                            title="Add 5"
                          >
                            +5
                          </button>
                        </div>
                      </td>
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
              {buttonText}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
