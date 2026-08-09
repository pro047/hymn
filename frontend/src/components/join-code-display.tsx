import { useState } from "react";

import { Button } from "./ui/button";

const COPY_IDLE_LABEL = "복사";
const COPY_DONE_LABEL = "복사됨";
const COPY_FAILED_LABEL = "복사 실패";

type JoinCodeDisplayProps = {
  code: string;
  /** Ties the code to whatever label the surrounding page gave it. */
  labelledBy?: string;
};

/**
 * Shows an invite code and offers to copy it. Shared by the signup success
 * panel and the church management page so the code is presented — and read
 * aloud — the same way wherever it appears.
 *
 * Copying is a convenience on top of a value that is always selectable: the
 * Clipboard API needs a secure context and a permission, so a failure has to
 * leave the code readable rather than replace it with an error.
 */
export default function JoinCodeDisplay({ code, labelledBy }: JoinCodeDisplayProps) {
  // The code it was copied from is kept alongside the label, so the label can
  // only ever describe the string on screen. Rotation replaces the code while
  // this component stays mounted, and a "복사됨" left over from the previous one
  // reads as "the new code is on your clipboard" when what is actually there is
  // the code the rotation just killed — handed on, it fails at the other end.
  const [attempt, setAttempt] = useState<{ code: string; label: string } | null>(null);
  // Derived rather than reset from an effect: an effect would show the new code
  // under the stale label for one frame, and this needs no frame at all.
  const copyLabel = attempt?.code === code ? attempt.label : COPY_IDLE_LABEL;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setAttempt({ code, label: COPY_DONE_LABEL });
    } catch {
      setAttempt({ code, label: COPY_FAILED_LABEL });
    }
  };

  return (
    <div className="flex items-center gap-2">
      <code
        aria-labelledby={labelledBy}
        className="flex-1 rounded-md bg-stone-100 px-3 py-2 text-center text-[18px] tracking-[0.3em] text-stone-900"
      >
        {code}
      </code>
      <Button type="button" variant="outline" size="sm" onClick={handleCopy}>
        {copyLabel}
      </Button>
    </div>
  );
}
