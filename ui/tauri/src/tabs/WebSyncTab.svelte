<script lang="ts">
  import { onMount } from "svelte";
  import VirtualTable from "../components/VirtualTable.svelte";
  import { app, errorText, setStatus, stale } from "../lib/app.svelte";
  import { idColumn } from "../lib/columns";
  import { fail, notify, pickFile } from "../lib/dialogs.svelte";
  import { call } from "../lib/rpc";
  import { startWebJob, web } from "../lib/web.svelte";
  import type { Column, Difference } from "../lib/types";

  /** Tab 7: compare a KiotViet location export with saved locations and resync the differences. */
  interface Row { product_id: string; web_code: string; web: string; local: string; status: string; missing: boolean }
  interface Workbook { sheets: Record<string, string[][]>; sheet: string; header_row: number }

  let url = $state("");
  let tabs = $state(1);
  let maxTabs = $state(10);
  let fileName = $state("");
  let differences = $state<Difference[]>([]);
  let missing = $state<{ product_id: string; web_code: string; local: string }[]>([]);
  let imported = $state(false);
  let busy = $state(false);
  let workbook = $state<Workbook | null>(null);
  let workbookPath = "";
  let sheet = $state("");
  let headerRow = $state(1);
  let idColumn_ = $state(0);
  let locationColumn = $state(1);
  let seen = -1;

  const resynced = $derived(new Set(web.purpose === "resync" ? web.finished : []));
  const pending = $derived(differences.filter((row) => !resynced.has(row.product_id)));
  const header = $derived(workbook?.sheets[sheet]?.[headerRow - 1] ?? []);
  const rows = $derived<Row[]>([
    ...differences.map((row) => ({
      product_id: row.product_id, web_code: row.web_code, web: row.wrong_location, local: row.true_location || "(none)", missing: false,
      status: resynced.has(row.product_id) ? "Saved; re-export to verify"
        : !row.true_location ? "Ready to clear web location"
        : row.true_location.includes(",") ? `Ready to sync ${row.true_location.split(",").length} locations` : "Unsynced",
    })),
    ...missing.map((row) => ({ product_id: row.product_id, web_code: row.web_code, web: "(not in export)", local: row.local, status: "Cannot compare", missing: true })),
  ]);
  const columns: Column<Row>[] = [
    idColumn<Row>(),
    { key: "web_code", label: "Web code (5-3-x)", width: "160px", value: (row) => row.web_code },
    { key: "web", label: "Website location", width: "minmax(140px, 1fr)", value: (row) => row.web },
    { key: "local", label: "Local location", width: "minmax(140px, 1fr)", value: (row) => row.local },
    { key: "status", label: "Status", width: "220px", value: (row) => row.status },
  ];

  onMount(() => {
    call<{ url: string; tabs: number; max_tabs: number }>("settings.get")
      .then((settings) => ([url, tabs, maxTabs] = [settings.url, settings.tabs, settings.max_tabs]))
      .catch((problem) => setStatus(errorText(problem)));
  });

  $effect(() => {
    if (stale("websync", seen)) {
      seen = app.changes.seq;
      if (imported) compare();
    }
  });

  export async function saveSettings(quiet = false): Promise<boolean> {
    try {
      const settings = await call<{ url: string; tabs: number }>("settings.save", { url, tabs });
      [url, tabs] = [settings.url, settings.tabs];
      if (!quiet) setStatus("KiotViet URL and upload tab count saved.");
      return true;
    } catch (problem) {
      if (!quiet) await fail(errorText(problem), "Settings not saved");
      return false;
    }
  }

  async function chooseWorkbook() {
    const path = await pickFile("Import KiotViet product locations", ["xlsx"], "Excel workbooks");
    if (!path) return;
    try {
      busy = true;
      workbook = await call<Workbook>("workbook.inspect", { path });
      workbookPath = path;
      [sheet, headerRow, idColumn_, locationColumn] = [workbook.sheet, workbook.header_row, 0, 1];
    } catch (problem) {
      await fail(errorText(problem), "Excel import failed");
    } finally {
      busy = false;
    }
  }

  async function compare(importing = false) {
    busy = true;
    try {
      const params = importing
        ? { path: workbookPath, sheet, header_row: headerRow, id_column: idColumn_, location_column: locationColumn }
        : {};
      const result = await call<{ web_products: number; differences: Difference[]; missing: { product_id: string; web_code: string; local: string }[] }>("compare.run", params);
      [differences, missing, imported] = [result.differences, result.missing, true];
      if (importing) {
        fileName = `${workbookPath.split(/[\\/]/).pop()}: ${result.web_products.toLocaleString()} website product IDs`;
        workbook = null;
        web.finished = [];
      }
    } catch (problem) {
      await fail(errorText(problem), importing ? "Import failed" : "Refresh failed");
    } finally {
      busy = false;
    }
  }

  async function resync() {
    if (!pending.length) return notify("There are no comparable unsynced products to upload.");
    if (!(await saveSettings())) return;
    await startWebJob("web.resync", { differences: pending }, `Resyncing web locations for ${pending.length} products…`, "resync");
  }

  async function exportExcel() {
    if (!pending.length) return notify("There are no different locations to export.");
    const path = await call<string>("compare.export", { differences: pending });
    setStatus(`Exported ${pending.length.toLocaleString()} unsynced location(s) to ${path}.`);
  }
</script>

<div class="tab-body" style:grid-template-rows="auto auto 1fr auto">
  <div class="panel">
    <div class="row">
      <label class="field grow">KiotViet Products URL<input bind:value={url} placeholder="https://yourstore.kiotviet.vn/man/#/Products" onblur={() => url.trim() && saveSettings(true)} /></label>
      <label class="field">Upload tabs<input type="number" min="1" max={maxTabs} bind:value={tabs} /></label>
      <button disabled={app.webBusy} onclick={() => saveSettings()}>Save settings</button>
    </div>
  </div>
  <div class="panel">
    <div class="row">
      <button disabled={busy || app.webBusy} onclick={chooseWorkbook}>Import Web's Data</button>
      <button disabled={busy || app.webBusy || !imported} onclick={() => compare()}>Refresh comparison</button>
      <button class="primary" disabled={busy || app.webBusy || !pending.length} onclick={resync}>Web resync</button>
      <button disabled={busy || !pending.length} onclick={exportExcel}>Export comparison Excel</button>
      <span class="muted">{busy ? "Working…" : fileName}</span>
    </div>
    {#if workbook}
      <div class="row chooser">
        <label class="field">Worksheet
          <select bind:value={sheet}>{#each Object.keys(workbook.sheets) as name (name)}<option>{name}</option>{/each}</select>
        </label>
        <label class="field">Header row<input type="number" min="1" bind:value={headerRow} /></label>
        <label class="field">Product ID column
          <select bind:value={idColumn_}>{#each header as name, index (index)}<option value={index}>{name || `Column ${index + 1}`}</option>{/each}</select>
        </label>
        <label class="field">Location column
          <select bind:value={locationColumn}>{#each header as name, index (index)}<option value={index}>{name || `Column ${index + 1}`}</option>{/each}</select>
        </label>
        <button class="primary" disabled={idColumn_ === locationColumn} onclick={() => compare(true)}>Import and compare</button>
        <button onclick={() => (workbook = null)}>Cancel</button>
      </div>
    {/if}
  </div>
  <div class="panel">
    <div class="fill">
      <VirtualTable {columns} {rows} rowKey={(row) => `${row.missing ? "m" : "d"}:${row.product_id}`}
        rowClass={(row) => (row.missing ? "muted" : resynced.has(row.product_id) ? "highlight" : "")}
        empty={imported ? "Every compared product matches." : "Import a KiotViet export to compare locations."} />
    </div>
  </div>
  <div class="row muted small">
    {#if imported}
      {pending.length.toLocaleString()} unsynced and ready for web resync · {missing.length.toLocaleString()} local IDs absent from export
    {/if}
    {#if app.webBusy && web.purpose === "resync"}· {web.progress}{/if}
  </div>
</div>

<style>
  .chooser { align-items: end; padding-top: 6px; border-top: 1px solid var(--line); }
</style>
