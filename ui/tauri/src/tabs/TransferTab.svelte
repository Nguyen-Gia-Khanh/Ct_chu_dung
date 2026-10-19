<script lang="ts">
  import CellPane from "../components/CellPane.svelte";
  import { app, applied, errorText, setStatus } from "../lib/app.svelte";
  import { askMerge, confirm, fail, notify } from "../lib/dialogs.svelte";
  import { call } from "../lib/rpc";
  import { startWebJob } from "../lib/web.svelte";
  import type { SlotAddress, WriteResult } from "../lib/types";

  /** Tab 5: switch two cells, or move one cell's contents into another. */
  let left = $state<SlotAddress | null>(null);
  let right = $state<SlotAddress | null>(null);
  let leftPane = $state<CellPane>();
  let rightPane = $state<CellPane>();
  let active: "left" | "right" = "left";
  let status = $state("Choose a cell on each side.");
  let moved = $state<string[]>([]);
  let scanSeen = 0;

  $effect(() => {
    if (app.tab === "transfer" && app.scan.seq !== scanSeen) {
      scanSeen = app.scan.seq;
      (active === "left" ? leftPane : rightPane)?.find(app.scan.code);
    }
  });

  function pair(): [SlotAddress, SlotAddress] | null {
    if (app.designerDirty) {
      notify("Commit or discard the Shelf Designer changes before switching or combining cells.");
      return null;
    }
    if (!left || !right) {
      notify("Choose a cell on both sides first.");
      return null;
    }
    if (left.slot_id === right.slot_id) {
      notify("Choose two different cells.");
      return null;
    }
    return [left, right];
  }

  async function swap() {
    const cells = pair();
    if (!cells || !(await confirm(`Switch all products between ${cells[0].slot_name} and ${cells[1].slot_name}?`))) return;
    try {
      const result = applied(await call<WriteResult & { counts: [number, number] }>("cells.swap", { first_slot_id: cells[0].slot_id, second_slot_id: cells[1].slot_id }));
      moved = result.changes.products;
      status = `Switched ${result.counts[0]} and ${result.counts[1]} product location(s) between ${cells[0].slot_name} and ${cells[1].slot_name}.`;
      setStatus(status);
    } catch (problem) {
      await fail(errorText(problem), "Cells were not switched");
    }
  }

  async function combine(direction: "right" | "left") {
    const cells = pair();
    if (!cells) return;
    const [source, target] = direction === "right" ? cells : [cells[1], cells[0]];
    if (!(await confirm(`Move every product from ${source.slot_name} into ${target.slot_name}?`))) return;
    try {
      let result = await call<WriteResult & { needs_merge?: string[] }>("cells.combine", { source_slot_id: source.slot_id, target_slot_id: target.slot_id });
      if (result.needs_merge) {
        if (!(await askMerge(result.needs_merge))) return;
        result = await call("cells.combine", { source_slot_id: source.slot_id, target_slot_id: target.slot_id, merge: true });
      }
      applied(result);
      moved = result.changes.products;
      status = `Combined ${result.count} product location(s) from ${source.slot_name} into ${target.slot_name}.`;
      setStatus(status);
    } catch (problem) {
      await fail(errorText(problem), "Cells were not combined");
    }
  }

  function modifyWeb() {
    if (!moved.length) {
      notify("No recent cell changes to modify on web. Switch or combine cells first.");
      return;
    }
    startWebJob("web.update_locations", { product_ids: moved, save_each: true }, `Updating web locations for ${moved.length} moved product(s)…`);
  }
</script>

<div class="tab-body" style:grid-template-columns="1fr auto 1fr">
  <CellPane bind:this={leftPane} title="Left cell" bind:address={left} onfocus={() => (active = "left")} />
  <div class="actions">
    <button class="primary" onclick={swap}>Switch cells ↔</button>
    <button onclick={() => combine("right")}>Combine left → right</button>
    <button onclick={() => combine("left")}>Combine right → left</button>
    <hr />
    <button disabled={app.webBusy || !moved.length} onclick={modifyWeb}>Modify location ID on web</button>
    <p class="muted small">{status}</p>
  </div>
  <CellPane bind:this={rightPane} title="Right cell" bind:address={right} onfocus={() => (active = "right")} />
</div>

<style>
  .actions { display: flex; flex-direction: column; gap: 8px; justify-content: center; width: 190px; }
  hr { width: 100%; border: 0; border-top: 1px solid var(--line); }
  p { margin: 0; }
</style>
