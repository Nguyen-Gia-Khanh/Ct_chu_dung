import React from 'react';
import { ActiveTab } from '../types';
import { BackendStatus } from '../services/backendStatus';

const tabs: { id: ActiveTab; label: string; description: string }[] = [
  { id: 'designer', label: 'Shelf Designer', description: 'Build, review, and commit shelf layouts.' },
  { id: 'assignment', label: 'Assign Locations', description: 'Prepare products and assign them to a shelf address.' },
  { id: 'primal_queue', label: 'Primal Queue / Shelves', description: 'Search the queue and inspect committed shelf contents.' },
  { id: 'browser', label: 'Browse Shelves', description: 'Explore saved shelves and their locations.' },
  { id: 'cell_transfer', label: 'Switch / Combine Cells', description: 'Move or combine the contents of committed cells.' },
  { id: 'exceptions', label: 'Special Exceptions', description: 'Manage multi-location stock and pending CSV updates.' },
];

interface WorkbenchChromeProps {
  activeTab: ActiveTab;
  onSelectTab: (tab: ActiveTab) => void;
  backendStatus: BackendStatus;
  children: React.ReactNode;
}

export const WorkbenchChrome: React.FC<WorkbenchChromeProps> = ({ activeTab, onSelectTab, backendStatus, children }) => {
  const current = tabs.find((tab) => tab.id === activeTab)!;
  return <div className="vscode-workbench">
    <header className="app-header-toolbar">
      <div className="app-brand-mark" aria-hidden="true">W</div>
      <div className="app-brand-copy">
        <span className="app-header-eyebrow">Warehouse operations</span>
        <strong className="app-header-title">Shelf Mapper</strong>
      </div>
      <div className="app-header-meta">Local workspace</div>
    </header>
    <nav className="vscode-tab-bar" role="tablist" aria-label="Warehouse workflows">
      {tabs.map(({ id, label }, index) => (
        <button
          key={id}
          type="button"
          role="tab"
          aria-selected={activeTab === id}
          aria-controls={`panel-${id}`}
          className={`vscode-tab ${activeTab === id ? 'active' : ''}`}
          onClick={() => onSelectTab(id)}
        >
          <span className="tab-index" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
          <span>{label}</span>
        </button>
      ))}
    </nav>
    <main className="vscode-content-view">
      <div className="workspace-heading">
        <div>
          <span className="workspace-kicker">WORKSPACE / {String(tabs.indexOf(current) + 1).padStart(2, '0')}</span>
          <h1>{current.label}</h1>
          <p>{current.description}</p>
        </div>
      </div>
      {children}
    </main>
    <footer className="vscode-status-bar" role="status">
      <span className="status-context">Warehouse Shelf Mapper</span>
      <span className="status-connection">
        <span className={`backend-indicator ${backendStatus}`} />
        {backendStatus === 'ready' ? 'Local database connected' : backendStatus === 'connecting' ? 'Connecting to local database…' : 'Local backend unavailable'}
      </span>
    </footer>
  </div>
};
