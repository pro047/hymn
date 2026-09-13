/** A fabric document, serialised. Held as a string rather than as the object
 * fabric hands back, for two reasons: two states can be compared with `===`,
 * and a stack of parsed documents costs several times the memory of the text
 * they came from. */
export type EditSnapshot = string;

/** How many steps back the editor can go.
 *
 * Measured (2026-09-12, fabric 7 in jsdom): one label is ~0.9KB, a label plus
 * twenty short strokes ~12.7KB, and one long freehand stroke adds ~5.7KB. So
 * twenty snapshots of a real sheet sit comfortably under a megabyte, and even
 * twenty of the largest document the server will store (MAX_EDIT_DOC_BYTES,
 * 1MB) is bounded rather than open-ended. The number itself is a judgement,
 * not a measurement: it is the depth a leader plausibly reaches for.
 */
export const HISTORY_LIMIT = 20;

export type EditHistory = {
  /** Makes `snapshot` the state the editor opened in, discarding everything
   * before it. Called when a canvas is built, and again for the next sheet. */
  reset: (snapshot: EditSnapshot) => void;
  /** Remembers a state the leader arrived at. */
  record: (snapshot: EditSnapshot) => void;
  /** Steps back one state and answers what to restore, or null at the bottom. */
  undo: () => EditSnapshot | null;
  canUndo: () => boolean;
  depth: () => number;
};

/** The states the sheet has been in, oldest first.
 *
 * There is no redo, so this is a plain stack rather than a cursor into a
 * timeline: undoing drops the state it left, and drawing after an undo simply
 * continues from where the leader now is.
 *
 * The bottom of the stack is the sheet as it opened. Keeping it there is what
 * makes "undo everything" land on the saved edit instead of on a blank sheet —
 * and what makes `canUndo` false at the start, when there is nothing of the
 * leader's own to take back yet.
 */
export function createEditHistory(limit: number = HISTORY_LIMIT): EditHistory {
  let states: EditSnapshot[] = [];

  return {
    reset(snapshot) {
      states = [snapshot];
    },

    record(snapshot) {
      // One gesture reaches this more than once — fabric fires object:added
      // and path:created for a single stroke, and a re-render can replay the
      // last event. Recording both would make one stroke take two presses to
      // undo, which reads as the button being broken.
      if (states[states.length - 1] === snapshot) return;
      states.push(snapshot);
      // The oldest state goes, not the newest: the most recent change must
      // always be undoable, whatever the cap. The cost is that a very long
      // session can no longer be taken all the way back to how it opened —
      // which is the cap doing its job rather than a defect.
      if (states.length > limit) states = states.slice(states.length - limit);
    },

    undo() {
      // Two, not one: the top of the stack is where the sheet *is*, so
      // undoing means dropping it and restoring what is underneath.
      if (states.length < 2) return null;
      states.pop();
      return states[states.length - 1];
    },

    canUndo() {
      return states.length > 1;
    },

    depth() {
      return states.length;
    },
  };
}
