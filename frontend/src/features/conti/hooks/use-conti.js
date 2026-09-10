import { useCallback, useEffect, useRef, useState } from "react";

import { apiFetch } from "../../../api/client";
import { API_PATHS } from "../../../api/paths";
import { alertMessageOf, readApiError, toFormError } from "../../../lib/api-error";
import { moveInGrid, splitPageAt, toOrderPayload, withPageBreaks } from "../../../lib/conti-order";
import { saveBlobAsFile } from "../../../lib/download";

const NETWORK_ERROR_MESSAGE = "네트워크 오류로 요청에 실패했습니다.";

/** Content-Disposition 의 filename. 없거나 형식이 다르면 null. */
function filenameFromResponse(response) {
  const header = response.headers?.get?.("Content-Disposition") ?? "";
  const match = header.match(/filename="?([^";]+)"?/);
  return match ? match[1] : null;
}

export function useConti(weekOfParam) {
  const [weekOf, setWeekOf] = useState(weekOfParam);
  const [pages, setPages] = useState(null);
  const [slotRatio, setSlotRatio] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [error, setError] = useState("");

  // The week the screen is on right now, readable from a response that was
  // sent for an earlier one. The GET effect can use its own `active` flag
  // because its cleanup runs on the way out; a PATCH has no cleanup to hang
  // that on, so it compares against this instead.
  const currentWeekRef = useRef(weekOfParam);
  useEffect(() => {
    currentWeekRef.current = weekOfParam;
  }, [weekOfParam]);

  // Every response that carries a whole conti lands here — the initial GET,
  // the reorder PATCH, and refresh below. Three copies of "which three fields
  // does a conti response set" would be three places to forget one.
  const applyConti = useCallback((data) => {
    setWeekOf(data.week_of);
    setSlotRatio(data.slot_ratio);
    setPages(data.pages);
  }, []);

  useEffect(() => {
    let active = true;
    setIsLoading(true);
    // Cleared, not just flagged loading: without this, moving from /conti/A
    // to /conti/B keeps A's songs painted while B loads, and if B's GET fails
    // A's conti stays on screen under an error alert — the leader would be
    // reordering week A believing it is week B.
    setPages(null);
    setSlotRatio(null);
    setWeekOf(weekOfParam);
    setError("");
    apiFetch(API_PATHS.weekConti(weekOfParam))
      .then(async (response) => {
        if (!active) return;
        if (!response.ok) {
          const apiError = await readApiError(response, "콘티를 불러오지 못했습니다.", []);
          setError(alertMessageOf(apiError));
          return;
        }
        applyConti(await response.json());
        setError("");
      })
      .catch(() => {
        if (active) setError(alertMessageOf(toFormError(NETWORK_ERROR_MESSAGE)));
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [weekOfParam, applyConti]);

  // No optimistic update: `next` only builds the PATCH body. The screen keeps
  // rendering the last `pages` the server sent, because reordering also moves
  // page breaks (chunk_pages) and a client-computed layout could show the
  // wrong split for a moment.
  //
  // Dragging and the up/down buttons share this one path: both are the same
  // edit — a song lands in a box — and the server answers both with the whole
  // conti. Two copies of the save would be two places for the error handling
  // to drift apart.
  const save = useCallback(
    async (next) => {
      setIsSaving(true);
      setError("");
      try {
        const response = await apiFetch(API_PATHS.weekContiOrder(weekOfParam), {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ items: toOrderPayload(next) }),
        });
        // A response for a week the screen has already left is dropped rather
        // than painted: the GET for the new week may well have landed first,
        // and this would repaint the old week's conti under the new week's
        // URL. The next drag would then PATCH the new week with the old
        // week's score_ids and take a 400 (ContiOrderMismatch).
        if (currentWeekRef.current !== weekOfParam) return;
        if (!response.ok) {
          const apiError = await readApiError(response, "순서를 저장하지 못했습니다.", []);
          setError(alertMessageOf(apiError));
          return;
        }
        applyConti(await response.json());
      } catch {
        if (currentWeekRef.current !== weekOfParam) return;
        setError(alertMessageOf(toFormError(NETWORK_ERROR_MESSAGE)));
      } finally {
        setIsSaving(false);
      }
    },
    [weekOfParam, applyConti]
  );

  // `from` and `to` are slot positions ({page, slot}), not list indexes: the
  // layout is what the leader edits, and the page breaks are read back out of
  // it by withPageBreaks rather than carried on the songs.
  const moveSlot = useCallback(
    async (from, to) => {
      // Guarded as well as disabled in the UI: a second edit started before the
      // first response lands would be computed from the pre-edit layout, and
      // whichever response arrived last would win.
      if (isSaving || !pages) return;
      const next = moveInGrid(pages, from, to);
      // Same reference means nothing moved, so the network is never touched.
      if (next === pages) return;
      await save(withPageBreaks(next));
    },
    [pages, isSaving, save]
  );

  // The scissors between two songs of one page. Dragging cannot say this —
  // it moves a song, and this moves only the boundary — and on a week whose
  // pages are all full there is no blank box to drag into at all.
  const splitPage = useCallback(
    async (position) => {
      if (isSaving || !pages) return;
      const next = splitPageAt(pages, position);
      // null means there is nothing to cut here; the control is not drawn in
      // that case, so this is the guard, not the common path.
      if (!next) return;
      await save(next);
    },
    [pages, isSaving, save]
  );

  /** Re-reads the week after something outside this hook changed a sheet.
   *
   * Deliberately does not blank `pages` the way the mount effect does: this
   * runs on the week already on screen, and clearing it would flash the whole
   * conti away to redraw one song. A failure leaves the previous conti up and
   * says nothing — the caller has already reported whatever went wrong, and
   * the songs on screen are still the songs in the week.
   */
  const refresh = useCallback(async () => {
    try {
      const response = await apiFetch(API_PATHS.weekConti(weekOfParam));
      if (currentWeekRef.current !== weekOfParam) return;
      if (!response.ok) return;
      applyConti(await response.json());
    } catch {
      // Same reason: nothing to add to what the caller already said.
    }
  }, [weekOfParam, applyConti]);

  const downloadPdf = useCallback(async () => {
    setIsDownloading(true);
    setError("");
    try {
      const response = await apiFetch(API_PATHS.weekPdf(weekOfParam));
      if (!response.ok) {
        const apiError = await readApiError(response, "PDF를 만들지 못했습니다.", []);
        setError(alertMessageOf(apiError));
        return;
      }
      const blob = await response.blob();
      // The server's own name first: `weekOf` starts out as the URL param and
      // is only corrected once the conti GET succeeds, so a failed (or still
      // pending) GET beside a successful PDF would otherwise save a Wednesday
      // name for a Sunday file. Content-Disposition carries the normalized
      // week (routes/conti.py:60); the state value is the fallback.
      saveBlobAsFile(blob, filenameFromResponse(response) ?? `conti-${weekOf}.pdf`);
    } catch {
      setError(alertMessageOf(toFormError(NETWORK_ERROR_MESSAGE)));
    } finally {
      setIsDownloading(false);
    }
  }, [weekOfParam, weekOf]);

  return {
    weekOf,
    pages,
    slotRatio,
    isLoading,
    isSaving,
    isDownloading,
    error,
    moveSlot,
    splitPage,
    downloadPdf,
    refresh,
  };
}
