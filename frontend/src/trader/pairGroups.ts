/**
 * Pure helpers for the owner's pair groups. A group is a shortcut for ticking several pairs at
 * once: it names pairs and trades nothing. Selecting a group copies its pairs into the selection;
 * what trades is the allowlist the owner saves (which needs a step-up when it adds anything).
 */

export interface PairGroup {
  name: string;
  pairs: string[];
}

export type GroupState = "all" | "some" | "none";

/** Whether every, some, or none of a group's pairs are in the selection. */
export function groupState(group: PairGroup, selected: ReadonlySet<string>): GroupState {
  if (group.pairs.length === 0) return "none";
  const hit = group.pairs.filter((p) => selected.has(p)).length;
  return hit === 0 ? "none" : hit === group.pairs.length ? "all" : "some";
}

/**
 * Tick or untick a group. Ticking adds its pairs. Unticking removes its pairs, except pairs that
 * belong to another group that is still fully ticked, so two overlapping groups do not undo each
 * other.
 */
export function toggleGroup(
  group: PairGroup,
  selected: readonly string[],
  groups: readonly PairGroup[],
): string[] {
  const current = new Set(selected);
  if (groupState(group, current) !== "all") {
    for (const p of group.pairs) current.add(p);
    return [...current].sort();
  }
  const keep = new Set<string>();
  for (const other of groups) {
    if (other.name !== group.name && groupState(other, current) === "all") {
      for (const p of other.pairs) keep.add(p);
    }
  }
  for (const p of group.pairs) if (!keep.has(p)) current.delete(p);
  return [...current].sort();
}

/** Add or replace a group; the name is trimmed and compared without case. */
export function upsertGroup(
  groups: readonly PairGroup[],
  name: string,
  pairs: readonly string[],
): PairGroup[] {
  const clean = name.replace(/\s+/g, " ").trim();
  const rest = groups.filter((g) => g.name.toLowerCase() !== clean.toLowerCase());
  return [...rest, { name: clean, pairs: [...new Set(pairs)].sort() }].sort((a, b) =>
    a.name.localeCompare(b.name),
  );
}

export function removeGroup(groups: readonly PairGroup[], name: string): PairGroup[] {
  return groups.filter((g) => g.name !== name);
}

/** A name the server will accept: 1 to 40 characters once spaces are collapsed. */
export function groupNameProblem(name: string): "empty" | "long" | null {
  const clean = name.replace(/\s+/g, " ").trim();
  if (clean.length === 0) return "empty";
  return clean.length > 40 ? "long" : null;
}
