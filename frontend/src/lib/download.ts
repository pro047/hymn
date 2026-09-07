// Isolated so a page test can vi.mock this module alone: jsdom has no real
// navigation, and clicking a real download link would hit its
// "Not implemented" warning instead of exercising the rest of the page.
export function saveBlobAsFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  // Attached before the click and revoked from a later task on purpose:
  // Firefox does not start a download from a detached anchor at all, and
  // revoking in the same task can abort a transfer already under way in
  // Firefox and Safari.
  document.body.appendChild(anchor);
  anchor.click();
  setTimeout(() => {
    anchor.remove();
    URL.revokeObjectURL(url);
  }, 0);
}
