import { describe, expect, it } from "vitest";
import { LightPolicyStore } from "./store.svelte";
import type { HassConnection } from "./types";

describe("LightPolicyStore gaming mappings", () => {
  it("uses the shared mutation states and resynchronises after saving", async () => {
    const messages: Record<string, unknown>[] = [];
    const connection: HassConnection = {
      async sendMessagePromise<T = unknown>(message: Record<string, unknown>): Promise<T> {
        messages.push(message);
        const type = message.type;
        if (type === "benni_light_policy/set_subentry_mappings") {
          return { mappings: message.mappings } as T;
        }
        if (type === "benni_light_policy/get_status") {
          return { apply_enabled: true, subentry_rules: [] } as T;
        }
        if (type === "benni_light_policy/get_look_map") {
          return { look_map: {}, subentry_rules: [] } as T;
        }
        if (type === "benni_scene_presets/list_looks") {
          return { looks: [{ slug: "cinema", name: "Cinema" }] } as T;
        }
        throw new Error(`Unexpected command: ${String(type)}`);
      },
    };
    const store = new LightPolicyStore();
    store.hass = { connection };

    await store.setSubentryMappings("gaming-ps5", { "1": "cinema" });

    expect(store.mutation).toMatchObject({ state: "success", action: "Gaming-Zuordnung speichern" });
    expect(messages.map((message) => message.type)).toEqual([
      "benni_light_policy/set_subentry_mappings",
      "benni_light_policy/get_status",
      "benni_light_policy/get_look_map",
      "benni_scene_presets/list_looks",
    ]);
    expect(store.looks).toEqual([{ slug: "cinema", name: "Cinema" }]);
  });

  it("keeps a missing connection visibly blocked", async () => {
    const store = new LightPolicyStore();

    await store.setSubentryMappings("gaming-ps5", { "1": "cinema" });

    expect(store.mutation).toMatchObject({ state: "blocked", message: "Keine Home-Assistant-Verbindung." });
  });
});
