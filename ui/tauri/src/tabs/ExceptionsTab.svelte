<script lang="ts">
  import VirtualTable from "../components/VirtualTable.svelte";
  import { app, applied, errorText, setStatus, stale } from "../lib/app.svelte";
  import { contentColumns, idColumn, productColumns } from "../lib/columns";
  import { confirm, fail, notify, pickFile } from "../lib/dialogs.svelte";
  import { call } from "../lib/rpc";
  import { normalizeSku } from "../lib/scanner";
  import type { Column, ContentRow, ProductRow, SearchResult, SlotAddress, StagedRow, WriteResult } from "../lib/types";

  /** Tab 6: extra locations for one product, products not yet in the catalog, and their CSV follow-up. */
  interface Multi { product_id: string; name: string; locations: string[] }

  let productId = $state("");
  let productName = $state("");
  let found = $state("");
  let stock = $state("");
  let floor = $state("");
  let side = $state("");
  let code = $state("");
  let rowText = $state("");
  let cellText = $state("");
  let address = $state<SlotAddress | null>(null);
  let contents = $state<ContentRow[]>([]);
  let contentSelected = $state<string[]>([]);
  let catalogQuery = $state("");
  let catalog = $state<SearchResult | null>(null);
  let multi = $state<Multi[]>([]);
  let staged = $state<StagedRow[]>([]);
  let stagedSelected = $state<string[]>([]);
  let listView = $state<"catalog" | "multi">("catalog");
  let seen = -1;
  let scanSeen = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const catalogColumns: Column<ProductRow>[] = [idColumn<ProductRow>(), productColumns.name];
  const multiColumns: Column<Multi>[] = [
    idColumn<Multi>(),
    { key: "name", label: "Product name", width: "minmax(120px, 1fr)", value: (row) => row.name },
    { key: "locations", label: "Locations", width: "minmax(140px, 1fr)", value: (row) => row.locations.join(", ") },
  ];
  const stagedColumns: Column<StagedRow>[] = [
    idColumn<StagedRow>(),
    { key: "name", label: "Full name", width: "minmax(120px, 1fr)", value: (row) => row.product_name },
    { key: "locations", label: "Locations", width: "minmax(120px, 0.8fr)", value: (row) => row.locations || row.staged_locations },
    { key: "status", label: "Status", width: "170px", value: stagedStatus },
    { key: "created", label: "Staged at", width: "150px", value: (row) => row.created_at },
  ];

  function stagedStatus(row: StagedRow): string {
    const missing = [!row.csv_updated && "CSV", !row.catalog_updated && "catalog"].filter(Boolean);
    return missing.length ? `Hasn't Add to: ${missing.join(" + ")}` : "Updated";
  }

  $effect(() => {
    if (stale("exceptions", seen)) {
      seen = app.changes.seq;
      refresh();
    }
  });

  $effect(() => {
    if (app.tab === "exceptions" && app.scan.seq !== scanSeen) {
      scanSeen = app.scan.seq;
      productId = app.scan.code;
      assign();
    }
  });

  async function refresh() {
    try {
      [catalog, multi, staged] = await Promise.all([
        call<SearchResult>("products.search", { query: catalogQuery, scope: "catalog" }),
        call<Multi[]>("exceptions.multi"),
        call<StagedRow[]>("exceptions.staged"),
      ]);
      if (address) contents = await call<ContentRow[]>("cells.contents", { slot_id: address.slot_id });
      if (productId.trim()) await findProduct();
    } catch (problem) {
      setStatus(errorText(problem));
    }
  }

  function searchCatalog() {
    clearTimeout(timer);
    timer = setTimeout(async () => (catalog = await call<SearchResult>("products.search", { query: catalogQuery, scope: "catalog" })), 150);
  }

  async function findProduct() {
    productId = normalizeSku(productId);
    if (!productId) return;
    const result = await call<{ name: string; locations: string[] } | null>("exceptions.find", { product_id: productId });
    if (!result) {
      found = `${productId} is not in the local catalog yet. Assigning it stages it for the CSV and catalog.`;
      return;
    }
    productName = result.name;
    found = result.locations.length
      ? `${result.locations.length > 1 ? "Multiple locations" : "Saved location"} for ${productId}: ${result.locations.join(", ")}`
      : `${productId} exists locally but has no saved location.`;
  }

  function pick(id: string, name = "") {
    productId = id;
    productName = name;
    findProduct();
  }

  async function loadAddress() {
    const [row, cell] = [Number(rowText), Number(cellText)];
    if (!floor.trim() || !side.trim() || !code.trim() || !(row >= 1) || !(cell >= 1)) {
      return notify("Enter floor, side, shelf, and a positive row and cell.");
    }
    address = await call<SlotAddress | null>("cells.address", { floor, side, code, row, cell });
    if (!address) return notify("That shelf cell does not exist.");
    contents = await call<ContentRow[]>("cells.contents", { slot_id: address.slot_id });
    setStatus(`Loaded ${address.slot_name}.`);
  }

  async function write(method: string, params: Record<string, unknown>, done: (result: WriteResult & { slot?: string }) => string) {
    try {
      const result = applied(await call<WriteResult & { slot?: string }>(method, params));
      setStatus(done(result));
      return true;
    } catch (problem) {
      await fail(errorText(problem), "Not saved");
      return false;
    }
  }

  async function assign() {
    productId = normalizeSku(productId);
    if (!productId) return notify("Enter or scan a product ID.");
    if (!address) return notify("Load the destination address first.");
    const initial = stock.trim() ? Number(stock) : null;
    if (initial !== null && !(Number.isSafeInteger(initial) && initial >= 0)) return notify("Initial shared stock must be a whole number (0 or more).");
    await write("exceptions.assign", { product_id: productId, slot_id: address.slot_id, stock: initial, name: productName.trim() || null },
      (result) => `Assigned ${productId} to ${result.slot}.`);
  }

  async function saveName() {
    if (!productId.trim() || !productName.trim()) return notify("Select a staged product and enter its name.");
    await write("exceptions.save_name", { product_id: productId, name: productName }, () => `Saved name for ${productId}.`);
  }

  async function removeFromCell() {
    const id = contentSelected[0];
    if (!address || !id) return notify("Select the product to remove in the loaded cell.");
    if (!(await confirm(`Remove ${id} from ${address.slot_name}?`))) return;
    await write("exceptions.remove", { product_id: id, slot_id: address.slot_id }, () => `Removed ${id} from ${address!.slot_name}.`);
  }

  const chosenStaged = () => (stagedSelected.length ? stagedSelected : null);

  async function appendCsv() {
    const path = await pickFile("Append staged products to a product CSV", ["csv", "txt"], "CSV files");
    if (!path) return;
    try {
      const result = await call<WriteResult>("exceptions.append_csv", { path, product_ids: chosenStaged() });
      applied(result, `Appended ${result.count} product(s) to the CSV.`);
    } catch (problem) {
      await fail(errorText(problem), "CSV was not updated");
    }
  }

  async function addCatalog() {
    const result = await call<WriteResult>("exceptions.add_catalog", { product_ids: chosenStaged() });
    applied(result, `Marked ${result.count} product(s) as added to the catalog.`);
  }

  async function wipe() {
    const id = stagedSelected[0];
    if (stagedSelected.length !== 1) return notify("Select exactly one staged product to wipe.");
    if (!(await confirm(`Wipe ${id} from staging, the catalog, and every saved shelf placement? This cannot be undone.`))) return;
    if (await write("exceptions.wipe", { product_id: id }, () => `Wiped ${id}.`)) [productId, productName] = ["", ""];
  }
</script>

<div class="tab-body" style:grid-template-columns="minmax(400px, 1fr) minmax(460px, 1.2fr)">
  <div class="panel">
    <h3>Product</h3>
    <div class="row nowrap">
      <input class="grow" bind:value={productId} placeholder="Product ID / barcode — Enter assigns"
        onkeydown={(event) => event.key === "Enter" && assign()} />
      <button onclick={findProduct}>Find ID</button>
    </div>
    <span class="muted small">{found}</span>
    <div class="row nowrap">
      <input class="grow" bind:value={productName} placeholder="Full name (for products not in the catalog)" />
      <button onclick={saveName}>Save name</button>
    </div>
    <form class="address" onsubmit={(event) => (event.preventDefault(), loadAddress())}>
      <label class="field">Floor<input bind:value={floor} /></label>
      <label class="field">Side<input bind:value={side} /></label>
      <label class="field">Shelf<input bind:value={code} /></label>
      <label class="field">Row<input bind:value={rowText} /></label>
      <label class="field">Cell<input bind:value={cellText} /></label>
      <button type="submit">Load address</button>
    </form>
    <div class="row nowrap">
      <label class="field grow">Initial shared stock (optional)<input bind:value={stock} inputmode="numeric" /></label>
      <button class="primary" onclick={assign}>Assign to {address?.slot_name ?? "loaded address"}</button>
    </div>
    <div class="segmented">
      <button class:active={listView === "catalog"} onclick={() => (listView = "catalog")}>Full catalog</button>
      <button class:active={listView === "multi"} onclick={() => (listView = "multi")}>Multiple locations ({multi.length})</button>
    </div>
    {#if listView === "catalog"}
      <input bind:value={catalogQuery} oninput={searchCatalog} placeholder="Search code, full name, or brand name" />
      <div class="fill">
        <VirtualTable columns={catalogColumns} rows={catalog?.rows ?? []} rowKey={(row) => row.product_id} onactivate={(row) => pick(row.product_id, row.name)} />
      </div>
      <span class="muted small">{catalog ? `${catalog.total.toLocaleString()} matching of ${catalog.size.toLocaleString()} products · showing ${catalog.rows.length}` : ""}</span>
    {:else}
      <div class="fill">
        <VirtualTable columns={multiColumns} rows={multi} rowKey={(row) => row.product_id} onselect={([id]) => id && pick(id)} />
      </div>
    {/if}
  </div>

  <div class="panel">
    <h3>{address ? `Cell ${address.slot_name}` : "No cell loaded"}</h3>
    <div class="cell">
      <VirtualTable columns={contentColumns.slice(0, 3)} rows={contents} rowKey={(row) => row.product_id} bind:selected={contentSelected}
        onselect={([id]) => id && pick(id, contents.find((row) => row.product_id === id)?.name)} />
    </div>
    <button class="danger" onclick={removeFromCell}>Remove product exception from this cell</button>
    <h3>Staged exceptions</h3>
    <div class="fill">
      <VirtualTable columns={stagedColumns} rows={staged} rowKey={(row) => row.product_id} multi bind:selected={stagedSelected}
        empty="Nothing is staged." onselect={(ids) => ids.length === 1 && pick(ids[0], staged.find((row) => row.product_id === ids[0])?.product_name)} />
    </div>
    <div class="row">
      <span class="muted small grow">{staged.length} staged product(s){stagedSelected.length ? ` · ${stagedSelected.length} selected` : " · actions apply to all"}</span>
      <button onclick={appendCsv}>Append back to CSV</button>
      <button onclick={addCatalog}>Add to catalog</button>
      <button class="danger" onclick={wipe}>Wipe</button>
    </div>
  </div>
</div>

<style>
  .address { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)) auto; gap: 6px; align-items: end; }
  .address input { width: 100%; }
  .cell { flex: 1 1 0; min-height: 0; }
</style>
