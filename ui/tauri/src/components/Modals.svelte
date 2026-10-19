<script lang="ts">
  import { modal, parseStock, MAX_STOCK } from "../lib/dialogs.svelte";

  /** Renders whichever in-app dialog is open (see dialogs.svelte.ts). */
  let values = $state<Record<string, string>>({});
  let columns = $state<number[]>([]);
  let problem = $state("");
  let current = $derived(modal.current);

  $effect(() => {
    const request = modal.current;
    problem = "";
    if (request?.kind === "stock") {
      values = Object.fromEntries(request.products.map((p) => [p.product_id, p.stock === null || p.stock === undefined ? "" : String(p.stock)]));
    } else if (request?.kind === "number") {
      values = { value: String(request.initial) };
    } else if (request?.kind === "columns") {
      columns = [...request.initial];
    }
  });

  function submit(event: Event) {
    event.preventDefault();
    const request = modal.current;
    if (!request) return;
    if (request.kind === "stock") {
      const result: Record<string, number> = {};
      for (const product of request.products) {
        const value = parseStock(values[product.product_id] ?? "");
        if (value === null) {
          problem = `${product.product_id}: enter a whole number of units from 0 to ${MAX_STOCK.toLocaleString()}.`;
          return;
        }
        result[product.product_id] = value;
      }
      request.resolve(result);
    } else if (request.kind === "number") {
      const value = parseStock(values.value ?? "");
      if (value === null) {
        problem = "Enter a whole number of units (0 or more).";
        return;
      }
      request.resolve(value);
    } else if (request.kind === "columns") {
      const chosen = columns.filter((index, position) => index >= 0 || !request.fields[position].optional);
      if (chosen.some((index) => index < 0) || new Set(chosen).size !== chosen.length) {
        problem = "Choose a different column for each field.";
        return;
      }
      request.resolve(columns);
    } else {
      request.resolve(true);
    }
  }

  function cancel() {
    const request = modal.current;
    if (!request) return;
    if (request.kind === "merge") request.resolve(false);
    else (request.resolve as (value: null) => void)(null);
  }
</script>

<svelte:window onkeydown={(event) => event.key === "Escape" && current && cancel()} />

{#if current}
  <div class="backdrop">
    <form class="dialog" onsubmit={submit}>
      {#if current.kind === "stock"}
        <h2>{current.title}</h2>
        <p class="muted">Destination: <strong>{current.destination}</strong>. Enter each product's stock (whole units, 0 or more).</p>
        <div class="list">
          {#each current.products as product, index (product.product_id)}
            <div class="line">
              <span class="id">{product.product_id}</span>
              <span class="grow name">{product.name}</span>
              <!-- svelte-ignore a11y_autofocus -->
              <input size="10" inputmode="numeric" autofocus={index === 0} bind:value={values[product.product_id]} />
            </div>
          {/each}
        </div>
        <p class="muted small">The assignment is saved immediately to this shelf address.</p>
      {:else if current.kind === "number"}
        <h2>{current.title}</h2>
        <p class="pre">{current.text}</p>
        <!-- svelte-ignore a11y_autofocus -->
        <input inputmode="numeric" autofocus bind:value={values.value} />
      {:else if current.kind === "columns"}
        <h2>{current.title}</h2>
        {#each current.fields as field, position (field.label)}
          <label class="field">
            {field.label}
            <select bind:value={columns[position]}>
              {#if field.optional}<option value={-1}>(none)</option>{/if}
              {#each current.headers as header, index (index)}
                <option value={index}>{header || `Column ${index + 1}`}</option>
              {/each}
            </select>
          </label>
        {/each}
      {:else}
        <h2>Products already in both cells</h2>
        <p>{current.products.join(", ")} {current.products.length === 1 ? "is" : "are"} saved in both cells.</p>
        <p class="muted">Merge keeps one location and one stock count per product (stock is never added up). Cancel leaves both cells unchanged.</p>
      {/if}
      {#if problem}<p class="error">{problem}</p>{/if}
      <div class="row actions">
        <button type="button" onclick={cancel}>Cancel</button>
        <button type="submit" class="primary">
          {current.kind === "merge" ? "Merge duplicates" : current.kind === "columns" ? "Import" : "OK"}
        </button>
      </div>
    </form>
  </div>
{/if}

<style>
  .backdrop { position: fixed; inset: 0; background: rgb(0 0 0 / 0.35); display: grid; place-items: center; z-index: 10; }
  .dialog { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px 18px; width: min(640px, 92vw); max-height: 86vh; display: flex; flex-direction: column; gap: 10px; box-shadow: 0 10px 30px rgb(0 0 0 / 0.25); }
  h2 { margin: 0; font-size: 15px; }
  p { margin: 0; }
  .pre { white-space: pre-line; }
  .list { overflow: auto; display: flex; flex-direction: column; gap: 4px; }
  .line { display: flex; gap: 8px; align-items: center; }
  .id { width: 120px; font-weight: 600; }
  .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .actions { justify-content: flex-end; }
</style>
