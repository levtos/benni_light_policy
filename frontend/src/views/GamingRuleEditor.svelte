<script lang="ts">
  import { Plus, RotateCcw, Save, Trash2 } from "@lucide/svelte";
  import CoverageBadge from "../lib/ui/CoverageBadge.svelte";
  import IconButton from "../lib/ui/IconButton.svelte";
  import Panel from "../lib/ui/Panel.svelte";
  import LookSelect from "../lib/light-policy/LookSelect.svelte";
  import { directLookCoverage } from "../lib/light-policy/contract";
  import {
    cleanGamingMappings,
    gamingDraftSignature,
    gamingMappingIssues,
    gamingMappingRows,
    gamingMappingsFromRows,
    gamingMappingsSignature,
    gamingSourceLabel,
    newGamingMappingRow,
    type GamingMappingRow,
  } from "../lib/light-policy/gaming-mappings";
  import type { LightPolicyStore } from "../lib/light-policy/store.svelte";
  import type { SubentryRule } from "../lib/light-policy/types";

  let { store, rule }: { store: LightPolicyStore; rule: SubentryRule } = $props();
  let rows = $state<GamingMappingRow[]>([]);
  let initialized = $state(false);
  let serverSignature = "";

  const subentryId = $derived(rule.subentry_id?.trim() ?? "");
  const sourceId = $derived(rule.source_id?.trim() ?? "");
  const incomingMappings = $derived(cleanGamingMappings(rule.mappings));
  const incomingSignature = $derived(gamingMappingsSignature(incomingMappings));
  const draftMappings = $derived(gamingMappingsFromRows(rows));
  const draftSignature = $derived(gamingDraftSignature(rows));
  const issues = $derived(gamingMappingIssues(rows));
  const dirty = $derived(draftSignature !== incomingSignature);

  $effect(() => {
    if (!initialized || (!dirty && incomingSignature !== serverSignature)) {
      rows = gamingMappingRows(incomingMappings);
      serverSignature = incomingSignature;
      initialized = true;
    }
  });

  const updateRow = (id: string, patch: Partial<Pick<GamingMappingRow, "classifierValue" | "lookRef">>) => {
    rows = rows.map((row) => (row.id === id ? { ...row, ...patch } : row));
  };

  const resetDraft = () => {
    rows = gamingMappingRows(incomingMappings);
    serverSignature = incomingSignature;
  };

  const save = async () => {
    if (!subentryId || issues.length || !dirty) return;
    await store.setSubentryMappings(subentryId, draftMappings);
    if (store.mutation.state === "success") serverSignature = gamingMappingsSignature(draftMappings);
  };
</script>

<Panel
  title={gamingSourceLabel(sourceId)}
  eyebrow={rule.title ? `${rule.title} · Gaming-Subentry` : "Gaming-Subentry"}
  description="Ein Classifier-Wert aktiviert genau den hier gewählten Scene-Presets-Look. Quelle und Classifier bleiben Eigentum der nativen HA-Subentry."
>
  {#snippet actions()}
    <button class="lp-button" type="button" onclick={() => (rows = [...rows, newGamingMappingRow()])} disabled={store.mutation.state === "pending"}>
      <Plus size={17} />Zuordnung
    </button>
    <button class="lp-button" type="button" onclick={resetDraft} disabled={!dirty || store.mutation.state === "pending"}>
      <RotateCcw size={17} />Entwurf verwerfen
    </button>
    <button class="lp-button primary" type="button" onclick={save} disabled={!dirty || Boolean(issues.length) || !subentryId || store.mutation.state === "pending"}>
      <Save size={17} />Speichern
    </button>
  {/snippet}

  <div class="lp-note" style="margin-bottom: 14px">
    Quelle: <strong>{sourceId || "nicht gesetzt"}</strong> · Classifier: <span class="technical-key">{rule.classifier_entity || "nicht gesetzt"}</span>
  </div>

  {#if issues.length}
    <div class="lp-note" style="margin-bottom: 14px; border-left-color: var(--lp-danger)">
      {issues.join(" ")}
    </div>
  {/if}

  {#if rows.length}
    <div class="lp-table-wrap">
      <table class="lp-table">
        <thead><tr><th>Classifier-Wert</th><th>Look</th><th>Coverage</th><th>Aktion</th></tr></thead>
        <tbody>
          {#each rows as row (row.id)}
            <tr>
              <td>
                <input
                  class="lp-input"
                  aria-label={`Classifier-Wert für ${gamingSourceLabel(sourceId)}`}
                  placeholder="z. B. 1"
                  value={row.classifierValue}
                  disabled={store.mutation.state === "pending"}
                  oninput={(event) => updateRow(row.id, { classifierValue: (event.currentTarget as HTMLInputElement).value })}
                />
              </td>
              <td>
                <LookSelect
                  value={row.lookRef}
                  looks={store.looks}
                  looksState={store.looksState}
                  disabled={store.mutation.state === "pending"}
                  onchange={(lookRef) => updateRow(row.id, { lookRef })}
                />
              </td>
              <td>
                <CoverageBadge coverage={directLookCoverage(`gaming:${subentryId}:${row.classifierValue || row.id}`, row.lookRef, store.indexedLooks, store.looksState)} />
              </td>
              <td>
                <IconButton
                  label="Zuordnung entfernen"
                  icon={Trash2}
                  onclick={() => (rows = rows.filter((candidate) => candidate.id !== row.id))}
                  disabled={store.mutation.state === "pending"}
                />
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else}
    <div class="lp-empty">Noch keine Classifier-Werte zugeordnet. „Zuordnung“ fügt einen lokalen Entwurf hinzu.</div>
  {/if}
</Panel>
