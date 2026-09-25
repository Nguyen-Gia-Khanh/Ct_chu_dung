import React, { useRef } from 'react';
import { ShelfCell } from '../types';

export function useCellTransferPaneSelection(
  items: ShelfCell['items'],
  setSelectedProductIds: React.Dispatch<React.SetStateAction<string[]>>,
) {
  const lastClickedPidRef = useRef<string | null>(null);

  const handleTableClick = (event: React.MouseEvent, productId: string) => {
    const allIds = items.map((item) => item.product_id);
    if (event.shiftKey && lastClickedPidRef.current) {
      const first = allIds.indexOf(lastClickedPidRef.current);
      const last = allIds.indexOf(productId);
      if (first >= 0 && last >= 0) {
        setSelectedProductIds((current) => Array.from(new Set([
          ...current,
          ...allIds.slice(Math.min(first, last), Math.max(first, last) + 1),
        ])));
      }
    } else if (event.ctrlKey || event.metaKey) {
      setSelectedProductIds((current) => current.includes(productId)
        ? current.filter((id) => id !== productId)
        : [...current, productId]);
      lastClickedPidRef.current = productId;
    } else {
      setSelectedProductIds([productId]);
      lastClickedPidRef.current = productId;
    }
  };

  return handleTableClick;
}
