import { describe, expect, it } from "vitest";
import {
  groupNameProblem,
  groupState,
  removeGroup,
  toggleGroup,
  upsertGroup,
  type PairGroup,
} from "@/trader/pairGroups";

const majors: PairGroup = { name: "Majors", pairs: ["BTCIDR", "ETHIDR"] };
const l1: PairGroup = { name: "L1", pairs: ["ETHIDR", "SOLIDR"] };

describe("pair groups", () => {
  it("reports whether all, some or none of a group is selected", () => {
    expect(groupState(majors, new Set())).toBe("none");
    expect(groupState(majors, new Set(["BTCIDR"]))).toBe("some");
    expect(groupState(majors, new Set(["BTCIDR", "ETHIDR", "XRPIDR"]))).toBe("all");
    expect(groupState({ name: "Empty", pairs: [] }, new Set(["BTCIDR"]))).toBe("none");
  });

  it("ticking a group adds its pairs; unticking removes them", () => {
    const on = toggleGroup(majors, ["XRPIDR"], [majors, l1]);
    expect(on).toEqual(["BTCIDR", "ETHIDR", "XRPIDR"]);
    expect(toggleGroup(majors, on, [majors, l1])).toEqual(["XRPIDR"]);
  });

  it("a partly ticked group is completed first, not cleared", () => {
    expect(toggleGroup(majors, ["BTCIDR"], [majors])).toEqual(["BTCIDR", "ETHIDR"]);
  });

  it("unticking keeps pairs that another fully ticked group still needs", () => {
    const both = toggleGroup(l1, toggleGroup(majors, [], [majors, l1]), [majors, l1]);
    expect(both).toEqual(["BTCIDR", "ETHIDR", "SOLIDR"]);
    // Majors off: ETH stays because L1 is still fully ticked.
    expect(toggleGroup(majors, both, [majors, l1])).toEqual(["ETHIDR", "SOLIDR"]);
  });

  it("saves a group sorted and de-duplicated, replacing one of the same name without case", () => {
    const first = upsertGroup([], "  Large   caps ", ["ETHIDR", "BTCIDR", "BTCIDR"]);
    expect(first).toEqual([{ name: "Large caps", pairs: ["BTCIDR", "ETHIDR"] }]);
    const again = upsertGroup([...first, majors], "LARGE CAPS", ["SOLIDR"]);
    expect(again.map((g) => g.name)).toEqual(["LARGE CAPS", "Majors"]);
    expect(again[0].pairs).toEqual(["SOLIDR"]);
  });

  it("removes a group by name", () => {
    expect(removeGroup([majors, l1], "L1")).toEqual([majors]);
  });

  it("checks a name the way the server does", () => {
    expect(groupNameProblem("   ")).toBe("empty");
    expect(groupNameProblem("x".repeat(41))).toBe("long");
    expect(groupNameProblem("x".repeat(40))).toBeNull();
    expect(groupNameProblem("  Large   caps ")).toBeNull();
  });
});
