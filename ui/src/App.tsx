import React, { useState, useEffect } from 'react';
import { ActiveTab } from './types';
import { Navbar } from './components/Navbar';
import { ShelfDesignerView } from './views/ShelfDesignerView';
import { LocationAssignmentView } from './views/LocationAssignmentView';
import { PrimalQueueView } from './views/PrimalQueueView';
import { ShelfBrowserView } from './views/ShelfBrowserView';
import { CellTransferView } from './views/CellTransferView';
import { ApiService } from './services/api';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<ActiveTab>('assignment');
  const [pendingCount, setPendingCount] = useState<number>(0);
  const [catalogCount, setCatalogCount] = useState<number>(0);

  useEffect(() => {
    loadCounts();
  }, [activeTab]);

  const loadCounts = async () => {
    try {
      const [pending, catalog] = await Promise.all([
        ApiService.getPendingQueue(),
        ApiService.getCatalog(),
      ]);
      setPendingCount(pending.length);
      setCatalogCount(catalog.length);
    } catch {
      // Ignore count load errors
    }
  };

  return (
    <div className="app-container">
      <Navbar
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        pendingCount={pendingCount}
        catalogCount={catalogCount}
      />

      <main className="app-content">
        {activeTab === 'designer' && <ShelfDesignerView />}
        {activeTab === 'assignment' && <LocationAssignmentView />}
        {activeTab === 'primal_queue' && <PrimalQueueView />}
        {activeTab === 'browser' && <ShelfBrowserView />}
        {activeTab === 'cell_transfer' && <CellTransferView />}
      </main>

      <footer className="ide-statusbar">
        <div className="statusbar-item">
          <span className="status-dot"></span>
          <span>Ready</span>
        </div>
        <div className="statusbar-item">
          <span>DB: <code>warehouse.db</code></span>
        </div>
        <div className="statusbar-spacer"></div>
        <div className="statusbar-item">
          <span>Catalog: <strong>{catalogCount}</strong> items</span>
        </div>
        <div className="statusbar-item">
          <span>Queue: <strong>{pendingCount}</strong> pending</span>
        </div>
        <div className="statusbar-item">
          <span>App: Desktop (TS)</span>
        </div>
      </footer>
    </div>
  );
};

export default App;
