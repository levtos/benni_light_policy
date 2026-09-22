import { describe, expect, it } from "vitest";
import {
  CANONICAL_PHASES,
  LEGACY_PHASES,
  brightnessProvenance,
  coverageFor,
  directLookCoverage,
  indexLooks,
  percentToRaw,
  rawToPercent,
} from "./contract";

describe("Light Policy UX contract", () => {
  it("keeps the primary matrix at nine phases and marks the two compatibility phases separately", () => {
    expect(CANONICAL_PHASES).toHaveLength(9);
    expect(CANONICAL_PHASES).toEqual([
      "early_night",
      "late_night",
      "early_morning",
      "forenoon",
      "midday",
      "afternoon",
      "late_afternoon",
      "evening",
      "late_evening",
    ]);
    expect(LEGACY_PHASES).toEqual(["late_morning", "early_evening"]);
  });

  it("distinguishes mapped, fallback, invalid, and missing references", () => {
    const looks = indexLooks([
      { slug: "soft", name: "Soft" },
      { slug: "fallback", name: "Fallback" },
    ]);
    const map = { spring_early_night: "soft", spring_late_night: "unknown" };
    const keys = ["spring_early_night", "spring_late_night", "spring_early_morning"];

    expect(coverageFor(keys[0], map, looks, "ready", keys)).toMatchObject({
      assignment: "mapped",
      status: "ready",
      ref: "soft",
    });
    expect(coverageFor(keys[1], map, looks, "ready", keys)).toMatchObject({
      assignment: "mapped",
      status: "invalid",
      ref: "unknown",
    });
    expect(coverageFor(keys[2], map, looks, "ready", keys)).toMatchObject({
      assignment: "fallback",
      status: "missing",
      notIndividuallyMaintained: true,
    });
  });

  it("treats a repeated existing reference as shared, not as an error", () => {
    const looks = indexLooks([{ slug: "soft", name: "Soft" }]);
    const map = { a: "soft", b: "soft" };
    expect(coverageFor("a", map, looks, "ready", ["a", "b"])).toMatchObject({
      status: "ready",
      isShared: true,
    });
  });

  it("does not convert an unavailable look catalog into a false missing diagnosis", () => {
    const coverage = coverageFor("spring_early_night", { spring_early_night: "soft" }, new Map(), "unavailable", ["spring_early_night"]);
    expect(coverage.status).toBe("unavailable");
    expect(coverage.availability).toBe("unavailable");
  });

  it("validates direct gaming look references without inventing fallback semantics", () => {
    const looks = indexLooks([{ slug: "cinema", name: "Cinema" }]);
    expect(directLookCoverage("gaming:ps5:1", "cinema", looks, "ready")).toMatchObject({ status: "ready", assignment: "mapped" });
    expect(directLookCoverage("gaming:ps5:2", "missing", looks, "ready")).toMatchObject({ status: "invalid", assignment: "mapped" });
    expect(directLookCoverage("gaming:ps5:3", "", looks, "ready")).toMatchObject({ status: "missing", assignment: "unassigned" });
  });

  it("round-trips the user-facing percentage with bounded backend raw values", () => {
    expect(percentToRaw(0)).toBe(0);
    expect(percentToRaw(100)).toBe(255);
    expect(percentToRaw(55)).toBe(140);
    expect(rawToPercent(255)).toBe(100);
    expect(rawToPercent(0)).toBe(0);
    expect(rawToPercent(300)).toBe(100);
  });

  it("exposes standard versus explicit provenance without claiming applied look state", () => {
    expect(brightnessProvenance("early_night", { early_night: 150 })).toMatchObject({ source: "standard", percent: 59 });
    expect(brightnessProvenance("early_night", { early_night: 80 })).toMatchObject({ source: "explicit", percent: 31 });
    expect(brightnessProvenance("winter_early_night", {})).toMatchObject({ source: "standard", percent: 59 });
    expect(brightnessProvenance("cinema", {})).toMatchObject({ source: "unavailable", raw: null, percent: null });
  });
});
