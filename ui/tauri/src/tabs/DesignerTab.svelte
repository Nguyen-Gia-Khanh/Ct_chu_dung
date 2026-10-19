<script lang="ts">
  import ShelfGrid from "../components/ShelfGrid.svelte";
  import Split from "../components/Split.svelte";
  import { app, applied, errorText, setStatus } from "../lib/app.svelte";
  import { askColumns, confirm, fail, notify, pickFile } from "../lib/dialogs.svelte";
  import { call } from "../lib/rpc";
  import type { GridModel, Shelf, ShelfView, WriteResult } from "../lib/types";

  /** Tab 1: shelf layouts (saved only on Commit) and CSV imports (saved immediately). */
  let shelves = $state<Shelf[]>([]);
  let chosen = $state<number | "">("");
  let shelfId = $state<number | null>(null);
  let floor = $state("1");
  let side = $state("1");
  let code = $state("");
  let rows = $state<number[]>([4, 4, 4]);
  let saved = $state(JSON.stringify([null, "1", "1", "", [4, 4, 4]]));
  let preview = $state<GridModel | null>(null);
  let problem = $state("");
  let seen = -1;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const snapshot = $derived(JSON.stringify([shelfId, floor.trim(), side.trim(), code.trim(), rows]));
  $effect(() => {
    app.designerDirty = snapshot !== saved && (shelfId !== null || code.trim() !== "");
  });

  $effect(() => {
    if (app.changes.seq !== seen) {
      seen = app.changes.seq;
      call<Shelf[]>("shelves.list").then((list) => (shelves = list));
    }
  });

  // Redraw the preview shortly after each edit.
  $effect(() => {
    void snapshot;
    clearTimeout(timer);
    timer = setTimeout(refreshPreview, 200);
  });

  async function refreshPreview() {
    if (!floor.trim() || !side.trim() || !code.trim()) {
      [preview, problem] = [null, "Enter floor, side, and shelf code."];
      return;
    }
    if (rows.some((count) => !Number.isInteger(count) || count < 1 || count > 200)) {
      [preview, problem] = [null, "Each row needs 1 to 200 cells."];
      return;
    }
    try {
      preview = await call<GridModel>("designer.preview", { floor, side, code, layout: rows, shelf_id: shelfId });
      problem = "";
    } catch (error) {
      [preview, problem] = [null, errorText(error)];
    }
  }

  function setRowCount(count: number) {
    if (!Number.isInteger(count) || count < 1 || count > 100) return;
    rows = count > rows.length ? [...rows, ...Array(count - rows.length).fill(4)] : rows.slice(0, count);
  }

  async function discardOk(): Promise<boolean> {
    return !app.designerDirty || confirm("Discard the shelf changes that have not been committed?");
  }

  async function newShelf() {
    if (!(await discardOk())) return;
    [shelfId, chosen, floor, side, code, rows] = [null, "", "1", "1", "", [4, 4, 4]];
    saved = snapshot;
    setStatus("Enter the new shelf metadata and row cell counts.");
  }

  async function loadShelf() {
    if (chosen === "") return notify("Select an existing shelf first.");
    if (!(await discardOk())) return;
    const view = await call<ShelfView>("shelves.grid", { shelf_id: chosen });
    [shelfId, floor, side, code, rows] = [view.shelf_id, view.floor, view.side, view.code, [...view.layout]];
    saved = JSON.stringify([shelfId, floor, side, code, rows]);
    setStatus(`Loaded ${view.label}.`);
  }

  async function commit() {
    await refreshPreview();
    if (!preview) return fail(problem, "Shelf layout cannot be saved");
    try {
      const result = await call<WriteResult & { shelf_id: number }>("designer.commit", { floor, side, code, layout: rows, shelf_id: shelfId });
      shelfId = result.shelf_id;
      chosen = result.shelf_id;
      saved = JSON.stringify([shelfId, floor.trim(), side.trim(), code.trim(), rows]);
      applied(result, `Committed Floor ${floor} / Side ${side} / Shelf ${code}.`);
      await notify(`Side ${side} / Shelf ${code} was saved.`, "Commit complete");
    } catch (error) {
      await fail(`Nothing was saved.\n\n${errorText(error)}`, "Commit failed");
    }
  }

  async function deleteShelf() {
    const shelf = shelves.find((item) => item.shelf_id === chosen);
    if (!shelf) return notify("Select an existing shelf first.");
    if (app.designerDirty) return notify("Commit or discard the pending Shelf Designer changes before deleting a saved shelf.");
    if (!(await confirm(`Delete ${shelf.label} and all its rows and cells?\n\nOnly empty shelves can be deleted. This saves immediately.`))) return;
    try {
      applied(await call<WriteResult>("designer.delete", { shelf_id: shelf.shelf_id }), `Deleted ${shelf.label}.`);
      chosen = "";
      if (shelfId === shelf.shelf_id) await newShelf();
    } catch (error) {
      await fail(errorText(error), "Shelf could not be deleted");
    }
  }

  async function importCsv(catalog: boolean) {
    const path = await pickFile(catalog ? "Import full product catalog" : "Import working products", ["csv", "txt"], "CSV files");
    if (!path) return;
    try {
      const info = await call<{ headers: string[]; rows: number; suggested: number[] }>("csv.inspect", { path, catalog });
      const columns = await askColumns({
        title: `Choose CSV columns (${info.rows.toLocaleString()} rows)`, headers: info.headers, initial: info.suggested,
        fields: [
          { label: "Product ID", optional: false },
          { label: catalog ? "Brand name (Honda)" : "Full name (Vietnamese)", optional: false },
          { label: catalog ? "Full name (optional)" : "Brand name (optional)", optional: true },
        ],
      });
      if (!columns) return;
      const result = applied(await call<WriteResult & { inserted: number; updated: number; skipped: number; duplicates: number }>("csv.import", {
        path, id_column: columns[0], name_column: columns[1], other_column: columns[2], catalog,
      }), "CSV import complete.");
      const label = catalog ? "catalog products" : "products";
      await notify(`New ${label}: ${result.inserted.toLocaleString()}\nExisting ${label} updated: ${result.updated.toLocaleString()}\n` +
        `Blank/invalid rows skipped: ${result.skipped.toLocaleString()}\nDuplicate IDs inside CSV: ${result.duplicates.toLocaleString()}\n\n` +
        (catalog ? "Warehouse assignments and the working queue were not changed." : "Shelf assignments, stock, and stored catalog names were kept."),
        "Import complete");
    } catch (error) {
      await fail(errorText(error), "Import failed");
    }
  }
</script>

<div class="tab-split">
  <div class="panel">
    <div class="row">
      <button onclick={() => importCsv(false)}>Import working products CSV</button>
      <button onclick={() => importCsv(true)}>Import full catalog CSV</button>
      <button onclick={newShelf}>New shelf</button>
      <span class="grow"></span>
      <select bind:value={chosen}>
        <option value="">Existing shelf…</option>
        {#each shelves as shelf (shelf.shelf_id)}<option value={shelf.shelf_id}>{shelf.label}</option>{/each}
      </select>
      <button onclick={loadShelf}>Load for editing</button>
      <button class="danger" onclick={deleteShelf}>Delete shelf</button>
      <button class="primary" onclick={commit}>Commit shelf design</button>
    </div>
  </div>
  <Split id="designer" sizes={[2, 3]} minPx={300} panes={[editorPane, previewPane]} />
</div>

{#snippet editorPane()}
  <div class="panel">
    <h3>{shelfId === null ? "New shelf" : "Editing saved shelf"}{app.designerDirty ? " · not committed" : ""}</h3>
    <div class="row nowrap">
      <label class="field grow">Floor<input bind:value={floor} /></label>
      <label class="field grow">Side<input bind:value={side} /></label>
      <label class="field grow">Shelf code<input bind:value={code} /></label>
      <label class="field">Rows<input type="number" min="1" max="100" value={rows.length} onchange={(event) => setRowCount(Number(event.currentTarget.value))} /></label>
    </div>
    <div class="row">
      <button disabled={rows.length >= 100} onclick={() => (rows = [...rows, 4])}>Add row at top</button>
      <button disabled={rows.length <= 1} onclick={() => (rows = rows.slice(0, -1))}>Remove top row</button>
    </div>
    <div class="editor">
      {#each [...rows.keys()].reverse() as index (index)}
        <label class="line">
          <span>Row {index + 1}{index === 0 ? " — ground" : ""}</span>
          <input type="number" min="1" max="200" bind:value={rows[index]} />
          <span class="muted small">cells across the row</span>
        </label>
      {/each}
    </div>
  </div>
{/snippet}

{#snippet previewPane()}
  <div class="panel">
    <h3>Preview</h3>
    {#if problem}<span class="error">{problem}</span>{/if}
    <div class="fill"><ShelfGrid grid={preview} message="The shelf preview appears here." /></div>
  </div>
{/snippet}

<style>
  .editor { overflow: auto; display: flex; flex-direction: column; gap: 4px; min-height: 0; flex: 1; }
  .line { display: grid; grid-template-columns: 120px 90px auto; gap: 8px; align-items: center; }
</style>
