import type {
  HassConnection,
  LightPolicyCatalog,
  LightPolicyStatus,
  LooksResponse,
  MutationSnapshot,
} from "./types";

const DOMAIN = "benni_light_policy";
const LOOKS_COMMAND = "benni_scene_presets/list_looks";

type JsonRecord = Record<string, unknown>;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function unwrap<T>(value: unknown): T {
  if (!isRecord(value)) return value as T;
  if (value.success === false) {
    throw new Error(String(value.error ?? value.message ?? "Home Assistant command failed"));
  }
  if ("result" in value && value.result !== undefined) return value.result as T;
  return value as T;
}

export class LightPolicyClient {
  constructor(private readonly connection: HassConnection) {}

  private async request<T>(type: string, payload: JsonRecord = {}): Promise<T> {
    const response = await this.connection.sendMessagePromise<unknown>({ type, ...payload });
    return unwrap<T>(response);
  }

  getStatus(): Promise<LightPolicyStatus> {
    return this.request<LightPolicyStatus>(`${DOMAIN}/get_status`);
  }

  getCatalog(): Promise<LightPolicyCatalog> {
    return this.request<LightPolicyCatalog>(`${DOMAIN}/get_look_map`);
  }

  listLooks(): Promise<LooksResponse> {
    return this.request<LooksResponse>(LOOKS_COMMAND);
  }

  setLookMap(lookMap: Record<string, string>): Promise<MutationSnapshot & JsonRecord> {
    return this.request<MutationSnapshot & JsonRecord>(`${DOMAIN}/set_look_map`, {
      look_map: lookMap,
    });
  }

  setSubentryMappings(
    subentryId: string,
    mappings: Record<string, string>,
  ): Promise<MutationSnapshot & JsonRecord> {
    return this.request<MutationSnapshot & JsonRecord>(`${DOMAIN}/set_subentry_mappings`, {
      subentry_id: subentryId,
      mappings,
    });
  }

  setApplyEnabled(enabled: boolean): Promise<MutationSnapshot & JsonRecord> {
    return this.request<MutationSnapshot & JsonRecord>(`${DOMAIN}/set_apply_enabled`, {
      enabled,
    });
  }

  setBrightnessProfile(
    brightnessProfile: Record<string, number>,
  ): Promise<MutationSnapshot & JsonRecord> {
    return this.request<MutationSnapshot & JsonRecord>(`${DOMAIN}/set_brightness_profile`, {
      brightness_profile: brightnessProfile,
    });
  }

  setCustomThemes(customThemes: string[]): Promise<MutationSnapshot & JsonRecord> {
    return this.request<MutationSnapshot & JsonRecord>(`${DOMAIN}/set_custom_themes`, {
      custom_themes: customThemes,
    });
  }
}
