<script lang="ts">
  import { onMount } from "svelte";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import Modals from "./components/Modals.svelte";
  import AssignTab from "./tabs/AssignTab.svelte";
  import BrowseTab from "./tabs/BrowseTab.svelte";
  import DesignerTab from "./tabs/DesignerTab.svelte";
  import ExceptionsTab from "./tabs/ExceptionsTab.svelte";
  import PrimalTab from "./tabs/PrimalTab.svelte";
  import TransferTab from "./tabs/TransferTab.svelte";
  import WebSyncTab from "./tabs/WebSyncTab.svelte";
  import { app, type TabId } from "./lib/app.svelte";
  import { confirm, notify } from "./lib/dialogs.svelte";
  import { call, onSidecar } from "./lib/rpc";
  import { ScannerDetector, normalizeSku } from "./lib/scanner";
  import { connectChrome, listenToJobs } from "./lib/web.svelte";

  const tabs: { id: TabId; label: string }[] = [
    { id: "designer", label: "1. Shelf Designer" },
    { id: "assign", label: "2. Assign Locations" },
    { id: "primal", label: "3. Primal Queue / Shelves" },
    { id: "browse", label: "4. Browse Shelves" },
    { id: "transfer", label: "5. Switch / Combine Cells" },
    { id: "exceptions", label: "6. Special Exceptions" },
    { id: "websync", label: "7. Web Location Sync" },
  ];
  const scanner = new ScannerDetector();
  let database = $state("");

  onMount(() => {
    listenToJobs();
    onSidecar("exit", () => (app.sidecarDown = true));
    onSidecar("ready", () => (app.sidecarDown = false));
    call<{ database: string }>("app.info").then((info) => (database = info.database)).catch(() => (app.sidecarDown = true));
    const window = getCurrentWindow();
    const unlisten = window.onCloseRequested(async (event) => {
      if (app.webBusy) {
        event.preventDefault();
        await notify("Wait for the current Chrome task before closing the mapper.", "Chrome task in progress");
      } else if (app.designerDirty && !(await confirm("Close without committing the Shelf Designer changes?"))) {
        event.preventDefault();
      }
    });
    return () => unlisten.then((stop) => stop());
  });

  /** A scanner burst ending in Enter goes to the active tab instead of the focused field. */
  function keydown(event: KeyboardEvent) {
    const code = scanner.feed(event.key, event.timeStamp);
    if (code) {
      event.preventDefault();
      event.stopPropagation();
      app.scan = { seq: app.scan.seq + 1, code: normalizeSku(code) };
    }
  }

  async function reconnect() {
    try {
      await call("app.info");
      app.sidecarDown = false;
      app.changes = { seq: app.changes.seq + 1, last: null };
    } catch {
      app.sidecarDown = true;
    }
  }
</script>

<svelte:window onkeydowncapture={keydown} />

<div class="shell">
  <nav class="tabs">
    {#each tabs as tab (tab.id)}
      <button class:active={app.tab === tab.id} onclick={() => (app.tab = tab.id)}>{tab.label}</button>
    {/each}
    <span class="grow"></span>
    <button class="chrome" class:ok={app.chromeConnected} disabled={app.webBusy} onclick={connectChrome}>
      {app.webBusy ? "Chrome busy…" : app.chromeConnected ? "Reconnect Chrome" : "Connect Chrome"}
    </button>
  </nav>

  {#if app.sidecarDown}
    <div class="banner">
      The data service is not running. <button onclick={reconnect}>Start it again</button>
      <span class="muted small">Details: data/logs/desktop-sidecar.log</span>
    </div>
  {/if}

  <main>
    <section hidden={app.tab !== "designer"}><DesignerTab /></section>
    <section hidden={app.tab !== "assign"}><AssignTab /></section>
    <section hidden={app.tab !== "primal"}><PrimalTab /></section>
    <section hidden={app.tab !== "browse"}><BrowseTab /></section>
    <section hidden={app.tab !== "transfer"}><TransferTab /></section>
    <section hidden={app.tab !== "exceptions"}><ExceptionsTab /></section>
    <section hidden={app.tab !== "websync"}><WebSyncTab /></section>
  </main>

  <footer>
    <span class="grow">{app.status}</span>
    <span class="muted small">{database}</span>
  </footer>
</div>

<Modals />

<style>
  .shell { height: 100%; display: flex; flex-direction: column; }
  nav, .banner, footer { flex: none; }
  .tabs { display: flex; gap: 2px; padding: 6px 10px 0; background: var(--panel); border-bottom: 1px solid var(--line); align-items: flex-end; }
  .tabs > button { border: 1px solid transparent; border-bottom: 0; border-radius: var(--radius) var(--radius) 0 0; background: transparent; padding: 6px 12px; }
  .tabs > button.active { background: var(--bg); border-color: var(--line); font-weight: 600; color: var(--accent); }
  .tabs > button.chrome { margin-bottom: 4px; border: 1px solid var(--line-strong); border-radius: var(--radius); }
  .tabs > button.chrome.ok { color: var(--ok); border-color: var(--ok); }
  .banner { padding: 6px 12px; background: var(--danger-soft); color: var(--danger); display: flex; gap: 10px; align-items: center; }
  main { flex: 1 1 auto; min-height: 0; }
  section { height: 100%; }
  section[hidden] { display: none; }
  footer { display: flex; gap: 12px; padding: 4px 12px; border-top: 1px solid var(--line); background: var(--panel); font-size: 12px; }
</style>
