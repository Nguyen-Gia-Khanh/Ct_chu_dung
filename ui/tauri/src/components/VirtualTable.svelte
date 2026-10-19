<script lang="ts" generics="T">
  /** A table that only draws the rows in view, so long lists scroll smoothly. */
  import type { Column } from "../lib/types";

  interface Props {
    columns: Column<T>[];
    rows: T[];
    rowKey: (row: T) => string;
    selected?: string[];
    multi?: boolean;
    rowClass?: (row: T) => string;
    empty?: string;
    onactivate?: (row: T) => void;
    onselect?: (keys: string[]) => void;
  }

  let {
    columns, rows, rowKey, selected = $bindable([]), multi = false, rowClass = () => "",
    empty = "Nothing to show.", onactivate, onselect,
  }: Props = $props();

  const ROW = 26;
  let scrollTop = $state(0);
  let height = $state(300);
  let anchor = $state<number | null>(null);

  const template = $derived(columns.map((column) => column.width ?? "minmax(80px, 1fr)").join(" "));
  const first = $derived(Math.max(0, Math.floor(scrollTop / ROW) - 5));
  const last = $derived(Math.min(rows.length, Math.ceil((scrollTop + height) / ROW) + 5));
  const visible = $derived(rows.slice(first, last));
  const chosen = $derived(new Set(selected));

  function choose(event: MouseEvent, index: number) {
    const key = rowKey(rows[index]);
    if (multi && event.shiftKey && anchor !== null) {
      const [from, to] = [Math.min(anchor, index), Math.max(anchor, index)];
      selected = rows.slice(from, to + 1).map(rowKey);
    } else if (multi && (event.ctrlKey || event.metaKey)) {
      selected = chosen.has(key) ? selected.filter((item) => item !== key) : [...selected, key];
      anchor = index;
    } else {
      selected = [key];
      anchor = index;
    }
    onselect?.(selected);
  }

  function display(value: string | number | null | undefined): string {
    return value === null || value === undefined ? "" : String(value);
  }
</script>

<div class="table" bind:clientHeight={height} onscroll={(event) => (scrollTop = event.currentTarget.scrollTop)}>
  <div class="head" style:grid-template-columns={template}>
    {#each columns as column (column.key)}
      <div class:right={column.align === "right"}>{column.label}</div>
    {/each}
  </div>
  {#if rows.length === 0}
    <div class="empty">{empty}</div>
  {/if}
  <div class="body" style:height="{rows.length * ROW}px">
    {#each visible as row, offset (rowKey(row))}
      {@const index = first + offset}
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <div
        class="tr {rowClass(row)}"
        class:selected={chosen.has(rowKey(row))}
        style:top="{index * ROW}px"
        style:grid-template-columns={template}
        role="row"
        tabindex="-1"
        aria-selected={chosen.has(rowKey(row))}
        onclick={(event) => choose(event, index)}
        ondblclick={() => onactivate?.(row)}
      >
        {#each columns as column (column.key)}
          <div class="td" class:right={column.align === "right"} title={display(column.value(row))}>
            {display(column.value(row))}
          </div>
        {/each}
      </div>
    {/each}
  </div>
</div>

<style>
  .table { position: relative; overflow: auto; height: 100%; min-height: 120px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--panel); }
  .head { position: sticky; top: 0; z-index: 1; display: grid; background: var(--panel-alt); border-bottom: 1px solid var(--line); font-weight: 600; font-size: 12px; color: var(--muted); }
  .head > div { padding: 5px 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .body { position: relative; }
  .tr { position: absolute; left: 0; right: 0; height: 26px; display: grid; align-items: center; cursor: default; user-select: none; }
  .tr:hover { background: var(--row-hover); }
  .tr.selected { background: var(--row-selected); }
  .tr.muted { color: var(--row-muted); }
  .tr.highlight { font-weight: 600; }
  .td { padding: 0 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .right { text-align: right; }
  .empty { padding: 16px; color: var(--muted); }
</style>
