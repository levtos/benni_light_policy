<script lang="ts">
  import Panel from "../lib/ui/Panel.svelte";
  import { isGamingRule } from "../lib/light-policy/gaming-mappings";
  import type { LightPolicyStore } from "../lib/light-policy/store.svelte";
  import GamingRuleEditor from "./GamingRuleEditor.svelte";

  let { store }: { store: LightPolicyStore } = $props();
  const rules = $derived(
    (store.status?.subentry_rules?.length ? store.status.subentry_rules : store.catalog?.subentry_rules ?? [])
      .filter(isGamingRule),
  );
</script>

<div class="lp-grid">
  <Panel
    title="Gaming"
    eyebrow="Classifier → Look"
    description="Jede konfigurierte Gaming-Quelle besitzt ihre eigene Zuordnung. Für PlayStation kann zum Beispiel der Classifier-Wert 1 auf den vorhandenen Cinema-Look zeigen."
  >
    <div class="lp-note">
      Diese Ansicht bearbeitet ausschließlich Look-Zuordnungen. Neue Quellen sowie `source_id`, Classifier-Entity und Priorität werden weiterhin unter Einstellungen → Geräte & Dienste → Light Policy als Gaming-Subentry angelegt.
    </div>
    {#if !rules.length}
      <div class="lp-empty" style="margin-top: 14px">
        Keine Gaming-Subentry konfiguriert. Lege zuerst in den nativen Home-Assistant-Integrationseinstellungen eine Gaming-Quelle an; danach erscheint sie hier automatisch.
      </div>
    {/if}
  </Panel>

  {#each rules as rule (rule.subentry_id)}
    <GamingRuleEditor {store} {rule} />
  {/each}
</div>
