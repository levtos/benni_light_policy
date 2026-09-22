import { describe, expect, it } from "vitest";
import {
  cleanGamingMappings,
  gamingMappingIssues,
  gamingMappingRows,
  gamingMappingsFromRows,
  gamingSourceLabel,
  newGamingMappingRow,
} from "./gaming-mappings";

describe("gaming mapping drafts", () => {
  it("round-trips cleaned classifier-to-look mappings", () => {
    const rows = gamingMappingRows({ " 2 ": " overwatch ", "1": " cinema " });
    expect(rows.map(({ classifierValue, lookRef }) => [classifierValue, lookRef])).toEqual([
      ["1", "cinema"],
      ["2", "overwatch"],
    ]);
    expect(gamingMappingsFromRows(rows)).toEqual({ "1": "cinema", "2": "overwatch" });
  });

  it("rejects incomplete and duplicate classifier rows before save", () => {
    const first = { ...newGamingMappingRow(), classifierValue: "1", lookRef: "cinema" };
    const duplicate = { ...newGamingMappingRow(), classifierValue: "1", lookRef: "overwatch" };
    const incomplete = { ...newGamingMappingRow(), classifierValue: "2" };
    expect(gamingMappingIssues([first, duplicate, incomplete])).toEqual([
      "Classifier-Wert 1 ist doppelt vorhanden.",
      "Jede Mapping-Zeile benötigt Classifier-Wert und Look.",
    ]);
  });

  it("drops blank persisted values and gives PS5 a user-facing label", () => {
    expect(cleanGamingMappings({ "": "cinema", "1": " ", "2": "cinema" })).toEqual({ "2": "cinema" });
    expect(gamingSourceLabel("ps5")).toBe("PlayStation 5");
  });
});
