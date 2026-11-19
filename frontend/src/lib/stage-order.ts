export type StageOrderPayloadItem = { score_id: string };

/**
 * Whole-week order after dropping activeId onto overId.
 *
 * Only the first visibleCount ids can move: the card draws five rows, and the
 * PATCH has to name every song of the week, so the rows it never drew ride
 * along behind in their own order. Null when nothing moves, so the caller
 * does not spend a request (30/minute) on a drop that changed nothing.
 */
export function reorderStage(
  weekIds: readonly string[],
  visibleCount: number,
  activeId: string,
  overId: string | null
): string[] | null {
  if (overId === null || activeId === overId) return null;

  const visible = weekIds.slice(0, visibleCount);
  const from = visible.indexOf(activeId);
  const to = visible.indexOf(overId);
  if (from === -1 || to === -1) return null;

  const moved = [...visible];
  moved.splice(from, 1);
  moved.splice(to, 0, activeId);
  return [...moved, ...weekIds.slice(visibleCount)];
}

/**
 * PATCH items with no starts_new_page key at all. The home card cannot see
 * the page breaks, and the server keeps a stored break only when the key is
 * absent; sending false would clear every break set on the conti screen.
 */
export function toStageOrderPayload(scoreIds: readonly string[]): StageOrderPayloadItem[] {
  return scoreIds.map((scoreId) => ({ score_id: scoreId }));
}

/**
 * `scores` rearranged to follow `ids`. Anything but an exact permutation
 * answers `scores` unchanged: a stale or partial id list must never drop or
 * duplicate a row on screen.
 */
export function orderScoresBy<T extends { id: string }>(
  scores: readonly T[],
  ids: readonly string[] | null
): T[] {
  if (ids === null || ids.length !== scores.length) return [...scores];

  const byId = new Map(scores.map((score) => [score.id, score] as const));
  const ordered: T[] = [];
  const seen = new Set<string>();
  for (const id of ids) {
    const score = byId.get(id);
    if (score === undefined || seen.has(id)) return [...scores];
    seen.add(id);
    ordered.push(score);
  }
  return ordered;
}
