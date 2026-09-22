import { describe, expect, it } from "vitest";
import { LightPolicyClient } from "./client";
import type { HassConnection } from "./types";

describe("LightPolicyClient", () => {
  it("sends the existing admin mapping command with only subentry id and cleaned mappings", async () => {
    const messages: Record<string, unknown>[] = [];
    const connection: HassConnection = {
      async sendMessagePromise<T = unknown>(message: Record<string, unknown>): Promise<T> {
        messages.push(message);
        return { result: { mappings: { "1": "cinema" } } } as T;
      },
    };

    await new LightPolicyClient(connection).setSubentryMappings("gaming-ps5", { "1": "cinema" });

    expect(messages).toEqual([{
      type: "benni_light_policy/set_subentry_mappings",
      subentry_id: "gaming-ps5",
      mappings: { "1": "cinema" },
    }]);
  });
});
