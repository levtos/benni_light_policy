import type { SubentryRule } from "./types";

export interface GamingMappingRow {
  id: string;
  classifierValue: string;
  lookRef: string;
}

let nextRowId = 0;

function rowId(): string {
  nextRowId += 1;
  return `gaming-mapping-${nextRowId}`;
}

export function cleanGamingMappings(value: Record<string, string> | null | undefined): Record<string, string> {
  return Object.fromEntries(
    Object.entries(value ?? {}).flatMap(([classifierValue, lookRef]) => {
      const cleanValue = classifierValue.trim();
      const cleanRef = typeof lookRef === "string" ? lookRef.trim() : "";
      return cleanValue && cleanRef ? [[cleanValue, cleanRef]] : [];
    }),
  );
}

export function gamingMappingRows(value: Record<string, string> | null | undefined): GamingMappingRow[] {
  return Object.entries(cleanGamingMappings(value))
    .sort(([left], [right]) => left.localeCompare(right, "de", { numeric: true }))
    .map(([classifierValue, lookRef]) => ({ id: rowId(), classifierValue, lookRef }));
}

export function newGamingMappingRow(): GamingMappingRow {
  return { id: rowId(), classifierValue: "", lookRef: "" };
}

export function gamingMappingsFromRows(rows: GamingMappingRow[]): Record<string, string> {
  return Object.fromEntries(
    rows.flatMap((row) => {
      const classifierValue = row.classifierValue.trim();
      const lookRef = row.lookRef.trim();
      return classifierValue && lookRef ? [[classifierValue, lookRef]] : [];
    }),
  );
}

export function gamingMappingsSignature(value: Record<string, string>): string {
  return JSON.stringify(Object.entries(cleanGamingMappings(value)).sort(([left], [right]) => left.localeCompare(right, "de", { numeric: true })));
}

export function gamingDraftSignature(rows: GamingMappingRow[]): string {
  return JSON.stringify(
    rows
      .map((row) => [row.classifierValue.trim(), row.lookRef.trim()])
      .sort(([left], [right]) => left.localeCompare(right, "de", { numeric: true })),
  );
}

export function gamingMappingIssues(rows: GamingMappingRow[]): string[] {
  const issues: string[] = [];
  const values = new Set<string>();
  for (const row of rows) {
    const classifierValue = row.classifierValue.trim();
    const lookRef = row.lookRef.trim();
    if (!classifierValue && !lookRef) {
      issues.push("Leere Mapping-Zeilen entfernen oder vollständig ausfüllen.");
      continue;
    }
    if (!classifierValue || !lookRef) {
      issues.push("Jede Mapping-Zeile benötigt Classifier-Wert und Look.");
      continue;
    }
    if (values.has(classifierValue)) issues.push(`Classifier-Wert ${classifierValue} ist doppelt vorhanden.`);
    values.add(classifierValue);
  }
  return [...new Set(issues)];
}

export function isGamingRule(rule: SubentryRule): boolean {
  return rule.type === "gaming";
}

export function gamingSourceLabel(sourceId: string | null | undefined): string {
  const source = sourceId?.trim().toLowerCase();
  if (source === "ps5") return "PlayStation 5";
  if (source === "pc") return "PC";
  if (source === "nintendo") return "Nintendo";
  return sourceId?.trim() || "Gaming-Quelle";
}
