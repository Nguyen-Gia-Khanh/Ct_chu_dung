import React from 'react';
import { ActiveTab } from '../types';
import { BackendStatus } from '../services/backendStatus';

const tabs: { id: ActiveTab; label: string }[] = [
  { id: 'designer', label: '1. Shelf Designer' },
  { id: 'assignment', label: '2. Assign Locations' },
  { id: 'primal_queue', label: '3. Primal Queue / Shelves' },
  { id: 'browser', label: '4. Browse Shelves' },
  { id: 'cell_transfer', label: '5. Switch / Combine Cells' },
  { id: 'exceptions', label: '6. Special Exceptions' },
];

interface WorkbenchChromeProps {
  activeTab: ActiveTab;
  onSelectTab: (tab: ActiveTab) => void;
  backendStatus: BackendStatus;
  children: React.ReactNode;
}

export const WorkbenchChrome: React.FC<WorkbenchChromeProps> = ({ activeTab, onSelectTab, backendStatus, children }) => (
  <div className="vscode-workbench">
    <header className="app-header-toolbar">
      <strong className="app-header-title">Warehouse Shelf Mapper</strong>
      <span className="app-header-subtitle">
        Shelf design · address assignment · primal queue · shelf browser · cell moves
      </span>
    </header>
    <nav className="vscode-tab-bar" role="tablist" aria-label="Warehouse workflows">
      {tabs.map(({ id, label }) => (
        <button
          key={id}
          type="button"
          role="tab"
          aria-selected={activeTab === id}
          aria-controls={`panel-${id}`}
          className={`vscode-tab ${activeTab === id ? 'active' : ''}`}
          onClick={() => onSelectTab(id)}
        >
          {label}
        </button>
      ))}
    </nav>
    <main className="vscode-content-view">{children}</main>
    <footer className="vscode-status-bar" role="status">
      <span className={`backend-indicator ${backendStatus}`} />
      {backendStatus === 'ready' ? 'Ready' : backendStatus === 'connecting' ? 'Connecting to local database…' : 'Local backend unavailable'}
    </footer>
  </div>
);
