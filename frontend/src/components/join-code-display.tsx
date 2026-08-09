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
  const [copyLabel, setCopyLabel] = useState(COPY_IDLE_LABEL);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopyLabel(COPY_DONE_LABEL);
    } catch {
      setCopyLabel(COPY_FAILED_LABEL);
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
