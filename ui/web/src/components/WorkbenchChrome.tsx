import React from 'react';
import { ActiveTab } from '../types';
import { BackendStatus } from '../services/backendStatus';

const tabs: { id: ActiveTab; label: string; description: string }[] = [
  { id: 'designer', label: 'Shelf Designer', description: 'Build and commit shelf layouts' },
  { id: 'assignment', label: 'Assign Locations', description: 'Prepare products and assign addresses' },
  { id: 'primal_queue', label: 'Primal Queue / Shelves', description: 'Search products and inspect shelves' },
  { id: 'browser', label: 'Browse Shelves', description: 'Explore saved shelves and cells' },
  { id: 'cell_transfer', label: 'Switch / Combine Cells', description: 'Move or combine cell contents' },
  { id: 'exceptions', label: 'Special Exceptions', description: 'Manage multi-location stock and CSV updates' },
];

interface WorkbenchChromeProps {
  activeTab: ActiveTab;
  onSelectTab: (tab: ActiveTab) => void;
  backendStatus: BackendStatus;
  children: React.ReactNode;
}

export const WorkbenchChrome: React.FC<WorkbenchChromeProps> = ({ activeTab, onSelectTab, backendStatus, children }) => {
  const current = tabs.find((tab) => tab.id === activeTab)!;

  return (
    <div className="workbench">
      <header className="workbench-titlebar">
        <div className="workbench-identity">
          <strong>Warehouse Mapper</strong>
          <span className="workbench-titlebar-divider" aria-hidden="true" />
          <span className="workbench-project">Local workspace</span>
        </div>
        <div className="workbench-connection" role="status">
          <span className={`backend-indicator ${backendStatus}`} />
          {backendStatus === 'ready' ? 'Database connected' : backendStatus === 'connecting' ? 'Connecting…' : 'Database unavailable'}
        </div>
      </header>

      <nav className="workbench-tabs" role="tablist" aria-label="Warehouse workflows">
        {tabs.map(({ id, label }, index) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={activeTab === id}
            aria-controls={`panel-${id}`}
            className={`workbench-tab ${activeTab === id ? 'active' : ''}`}
            onClick={() => onSelectTab(id)}
          >
            <span className="workbench-tab-index" aria-hidden="true">{index + 1}</span>
            {label}
          </button>
        ))}
      </nav>

      <main className="workbench-content">
        <div className="workbench-context">
          <h1>{current.label}</h1>
          <span>{current.description}</span>
        </div>
        {children}
      </main>
    </div>
  );
};
