import { useCallback, useEffect, useRef, useState } from "react";

/** Used only when the box has not been laid out yet.
 *
 * jsdom has no layout at all, so clientWidth is 0 there and every zoom
 * computed from it would be too. A real browser hits this only on the frame
 * before the dialog is measured.
 */
const FALLBACK_BOX = { width: 880, height: 620 };

/** How far in and out the buttons go, and by how much each press moves.
 *
 * Capped rather than open-ended: past 4x a 538px scan is mostly interpolation,
 * and below the fit the sheet is too small to write on. 1 is always reachable
 * because the steps are multiplicative from it.
 */
const ZOOM_STEP = 1.25;
const MIN_SCALE = 1;
const MAX_SCALE = 4;

export const BRUSH_WIDTH = 3;
export const TEXT_SIZE = 24;

/** Drives one fabric canvas: the song's sheet as the background, the leader's
 * markings as objects on top.
 *
 * Kept apart from the dialog so the two can be read separately — this file is
 * the only place that knows fabric exists, and the dialog is ordinary React
 * around it.
 *
 * `editDoc` seeds the canvas once, on open. It is deliberately not watched for
 * later changes: the canvas *is* the working copy from then on, and re-seeding
 * from a prop would throw away whatever had been drawn since.
 */
export function useFabricSheet({ canvasRef, containerRef, sourceImageUrl, editDoc }) {
  const fabricRef = useRef(null);
  const imageRef = useRef(null);
  // The zoom that makes the whole sheet fit the box, and the multiple of it
  // the buttons are currently on. They are kept apart so that "맞춤" is a
  // value to return to rather than a measurement to redo.
  const fitZoomRef = useRef(1);
  const zoomRef = useRef(1);
  const [scale, setScale] = useState(1);
  // Derived from fitZoomRef when it was a computed value, which meant a
  // re-fit that left the scale alone changed nothing React could see: a ref
  // does not re-render, and setScale(sameValue) bails out. Held as state so
  // the label follows the sheet through a window resize.
  const [zoomPercent, setZoomPercent] = useState(100);
  // The observer below needs the current scale but must not be torn down and
  // rebuilt every time it changes — a resubscribe on each zoom press would
  // fire an extra measurement mid-gesture.
  const scaleRef = useRef(1);
  const [isReady, setIsReady] = useState(false);
  const [mode, setMode] = useState("draw");
  const [color, setColor] = useState("#dc2626");
  const [hasSelection, setHasSelection] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);

  // The seed is read once per canvas, so it is held in a ref rather than
  // listed as a dependency: putting editDoc in the effect below would rebuild
  // the canvas — and lose the current drawing — every time the parent
  // re-rendered with a new object identity for the same document.
  const seedRef = useRef(editDoc);
  useEffect(() => {
    seedRef.current = editDoc;
  }, [editDoc]);

  /** The drawing area's size right now, or a stand-in before it has one. */
  const boxSize = useCallback(() => {
    const box = containerRef?.current;
    // clientWidth counts padding, which the sheet cannot be drawn in, so the
    // measured element carries none — see the dialog. Subtracting a computed
    // padding instead would be a second place for the two to disagree, and
    // one that no test can see: jsdom loads no stylesheet, so every computed
    // padding there is the empty string.
    return {
      width: box?.clientWidth || FALLBACK_BOX.width,
      height: box?.clientHeight || FALLBACK_BOX.height,
    };
  }, [containerRef]);

  /** The zoom at which the whole sheet fits the box, for the box's size now.
   *
   * Recomputed rather than remembered because the box changes size — the
   * window resizes, and on the first frames it may not have been laid out at
   * all. A fit measured once, at whatever moment the image happened to
   * finish loading, is wrong for every size but that one.
   */
  const fitZoomFor = useCallback(
    (image) => {
      const box = boxSize();
      return Math.min(box.width / image.width, box.height / image.height);
    },
    [boxSize]
  );

  /** Puts the canvas on `fit x next` without rebuilding it.
   *
   * Both the element's size and the viewport transform, because they answer
   * different questions: the element decides how much room the scroll box has
   * to give, the transform decides where a click lands in the image.
   */
  const applyScale = useCallback((canvas, next) => {
    const image = imageRef.current;
    if (!canvas || !image) return;
    const zoom = fitZoomRef.current * next;
    zoomRef.current = zoom;
    canvas.setDimensions({ width: image.width * zoom, height: image.height * zoom });
    canvas.setZoom(zoom);
    canvas.requestRenderAll();
    scaleRef.current = next;
    setScale(next);
    setZoomPercent(Math.round(zoom * 100));
  }, []);

  useEffect(() => {
    const element = canvasRef.current;
    if (!element || !sourceImageUrl) return undefined;

    let cancelled = false;
    let canvas = null;
    setIsReady(false);
    setLoadFailed(false);

    // Imported here rather than at module scope so fabric's ~300KB is fetched
    // when a leader opens the editor, not on every page of the app.
    import("fabric")
      .then(async ({ Canvas, FabricImage, PencilBrush }) => {
        // crossOrigin, and it has to be set before the request goes out: the
        // sheet comes from S3 on another origin, and a canvas that has drawn
        // an image fetched without CORS is tainted — toDataURL on it throws a
        // SecurityError, which is the last step of saving. The bucket allows
        // this origin already (infra/modules/s3_bucket, allowed_origins).
        // originX/originY, and they are not the default: fabric 7 places every
        // object by its *centre*, so a background at left:0 top:0 hangs half
        // off the top and half off the left — the canvas then shows only the
        // sheet's bottom-right quarter, at the correct scale, which reads as
        // "the image is cropped" rather than as "the origin is wrong".
        // Three arguments, and the split matters: the second bag is how to
        // *fetch* the image and the third is what the object becomes. Passing
        // originX in the second one is accepted and silently dropped.
        const image = await FabricImage.fromURL(
          sourceImageUrl,
          { crossOrigin: "anonymous" },
          { originX: "left", originY: "top", left: 0, top: 0 }
        );
        if (cancelled) return;

        canvas = new Canvas(element, { selection: true, preserveObjectStacking: true });
        fabricRef.current = canvas;

        imageRef.current = image;
        // Contained, not fitted to the width: scores are portrait, and a sheet
        // sized to the box's width runs several screens tall — which is what
        // the first version did, and why it opened mid-page with no way to
        // reach the rest of it.
        fitZoomRef.current = fitZoomFor(image);
        // The objects keep the image's own coordinates; only the view is
        // scaled. That is what lets a sheet drawn on one screen reopen
        // correctly on another, and what makes the export a plain 1/zoom.
        applyScale(canvas, 1);

        // Replayed before the background is attached, because loadFromJSON
        // replaces the whole canvas — including its background — with what
        // the document says, and the document deliberately does not carry one
        // (a presigned URL expires; see exportSheet below).
        if (seedRef.current) {
          await canvas.loadFromJSON(seedRef.current);
          if (cancelled) return;
        }

        canvas.backgroundImage = image;
        canvas.freeDrawingBrush = new PencilBrush(canvas);
        canvas.requestRenderAll();

        const syncSelection = () => setHasSelection(Boolean(canvas.getActiveObject()));
        canvas.on("selection:created", syncSelection);
        canvas.on("selection:updated", syncSelection);
        canvas.on("selection:cleared", syncSelection);

        setIsReady(true);
      })
      .catch(() => {
        if (!cancelled) setLoadFailed(true);
      });

    return () => {
      cancelled = true;
      fabricRef.current = null;
      imageRef.current = null;
      setIsReady(false);
      // StrictMode mounts twice in development, so this runs against a canvas
      // that may still be mid-load; dispose() on an already-disposed canvas
      // rejects rather than throwing synchronously, and there is nothing left
      // to tell the user about at that point.
      canvas?.dispose().catch(() => {});
    };
  }, [canvasRef, sourceImageUrl, fitZoomFor, applyScale]);

  // Re-fits whenever the box changes size, which is also what corrects a fit
  // computed before the dialog had been laid out. The observer fires once on
  // observe() with the real size, so the sheet lands right even if the
  // measurement above happened too early to be worth anything.
  useEffect(() => {
    const box = containerRef?.current;
    if (!box || !isReady || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(() => {
      const canvas = fabricRef.current;
      const image = imageRef.current;
      if (!canvas || !image) return;
      fitZoomRef.current = fitZoomFor(image);
      // The leader's own zoom is kept: a window resize should move the sheet
      // with the box, not undo the enlarging they just did.
      applyScale(canvas, scaleRef.current);
    });
    observer.observe(box);
    return () => observer.disconnect();
  }, [containerRef, isReady, fitZoomFor, applyScale]);

  // Mode and colour are applied to the live canvas rather than baked in at
  // creation: switching either must not rebuild the canvas, which would drop
  // everything drawn so far.
  useEffect(() => {
    const canvas = fabricRef.current;
    if (!canvas || !isReady) return undefined;

    canvas.isDrawingMode = mode === "draw";
    if (canvas.freeDrawingBrush) {
      canvas.freeDrawingBrush.color = color;
      canvas.freeDrawingBrush.width = BRUSH_WIDTH;
    }
    if (mode !== "select") {
      // Handles left on screen while another tool is active read as "this is
      // still selected", and the next click would move that object instead of
      // drawing.
      canvas.discardActiveObject();
      canvas.requestRenderAll();
    }

    if (mode !== "text") return undefined;

    const placeText = async (event) => {
      // A click that landed on something already drawn is a click *on* that
      // thing. Making a new label there would stack an empty one over it —
      // the old label could never be reached again, and clicking away to
      // finish typing would itself drop another empty object onto the sheet.
      if (event.target) return;
      const { IText } = await import("fabric");
      // Scene coordinates, not the raw pointer: the canvas is zoomed, and the
      // two disagree by exactly that factor.
      const point = canvas.getScenePoint(event.e);
      const text = new IText("", {
        left: point.x,
        top: point.y,
        fontSize: TEXT_SIZE,
        fill: color,
      });
      canvas.add(text);
      canvas.setActiveObject(text);
      // Straight into editing: a leader who has just placed a label wants to
      // type it, and an empty IText left un-edited is an invisible object
      // nobody can select again.
      text.enterEditing();
      canvas.requestRenderAll();
    };

    // An IText left empty is invisible and unselectable, so it can only be
    // removed by the code that made it. Dropped whenever editing ends rather
    // than only on the text tool's watch: a label can also be emptied later,
    // from the select tool, and it is just as unreachable then.
    const dropEmptyText = (event) => {
      const text = event.target;
      if (text && !text.text?.trim()) canvas.remove(text);
    };

    canvas.on("mouse:down", placeText);
    canvas.on("text:editing:exited", dropEmptyText);
    return () => {
      canvas.off("mouse:down", placeText);
      canvas.off("text:editing:exited", dropEmptyText);
    };
  }, [mode, color, isReady]);

  const zoomBy = useCallback(
    (factor) => {
      const next = Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale * factor));
      applyScale(fabricRef.current, next);
    },
    [scale, applyScale]
  );

  const zoomIn = useCallback(() => zoomBy(ZOOM_STEP), [zoomBy]);
  const zoomOut = useCallback(() => zoomBy(1 / ZOOM_STEP), [zoomBy]);
  const zoomToFit = useCallback(() => applyScale(fabricRef.current, 1), [applyScale]);

  const deleteSelected = useCallback(() => {
    const canvas = fabricRef.current;
    if (!canvas) return;
    // getActiveObjects, not getActiveObject: a rubber-band selection is one
    // group object, and removing the group would leave its members behind.
    canvas.getActiveObjects().forEach((object) => canvas.remove(object));
    canvas.discardActiveObject();
    setHasSelection(false);
    canvas.requestRenderAll();
  }, []);

  /** The two shapes the edit is stored in: the flattened sheet, and the
   * objects it was flattened from.
   *
   * multiplier undoes the display zoom, so the PNG comes out at the image's
   * own resolution rather than whatever this screen happened to show.
   *
   * backgroundImage is stripped from the document on purpose. fabric puts the
   * image's `src` in there, and that src is a presigned URL — storing it would
   * write a fifteen-minute credential into the row and reopen to a broken
   * background once it expired. The server hands back a fresh one instead.
   */
  const exportSheet = useCallback(() => {
    const canvas = fabricRef.current;
    if (!canvas) return null;
    // toDataURL throws SecurityError on a canvas that has drawn an image
    // fetched without CORS — a bucket rule that changes, or a presigned GET
    // the browser already had cached from a plain <img>. Left to propagate it
    // becomes an unhandled rejection inside an async onClick: no message, no
    // error state, and a save button that looks like it did nothing.
    // Otherwise the active object's outline is painted into the saved sheet.
    canvas.discardActiveObject();
    canvas.requestRenderAll();
    const dataUrl = canvas.toDataURL({ format: "png", multiplier: 1 / zoomRef.current });
    const { backgroundImage: _background, ...doc } = canvas.toJSON();
    return { dataUrl, doc };
  }, []);

  return {
    isReady,
    loadFailed,
    scale,
    // Against the sheet's own pixels, not against the fit: "this is half the
    // size the file is" is the number that says whether reading it will be
    // hard, and it is also the one that makes a wrong fit visible.
    zoomPercent,
    canZoomIn: scale < MAX_SCALE,
    canZoomOut: scale > MIN_SCALE,
    zoomIn,
    zoomOut,
    zoomToFit,
    mode,
    setMode,
    color,
    setColor,
    hasSelection,
    deleteSelected,
    exportSheet,
  };
}
