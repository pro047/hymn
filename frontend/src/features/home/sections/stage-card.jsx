import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { orderScoresBy, reorderStage } from "../../../lib/stage-order";

const VISIBLE_COUNT = 5;

function ScoreRow({ score, index, canManage, onUpdate, onDelete, handle = null, rowProps = {} }) {
  return (
    <div
      {...rowProps}
      className={`grid ${
        handle ? "grid-cols-[auto_auto_1fr_auto]" : "grid-cols-[auto_1fr_auto]"
      } items-center gap-3 rounded-md border border-stone-200 bg-white p-3`}
    >
      {handle}
      <span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-stone-100 text-xs font-semibold text-stone-700">
        {index + 1}
      </span>
      {canManage ? (
        <button
          type="button"
          className="truncate text-left text-sm font-medium text-stone-900"
          onClick={() => onUpdate(score)}
        >
          {score.title}
        </button>
      ) : (
        <span className="truncate text-left text-sm font-medium text-stone-900">{score.title}</span>
      )}
      {canManage ? (
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" type="button" onClick={() => onUpdate(score)}>
            수정
          </Button>
          <Button
            variant="ghost"
            size="sm"
            type="button"
            className="text-red-600 hover:bg-red-50 hover:text-red-700"
            onClick={() => onDelete(score.id)}
          >
            삭제
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function SortableScoreRow({ score, index, locked, onUpdate, onDelete }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition } =
    useSortable({ id: score.id, disabled: locked });

  // The listeners sit on the handle alone, with setActivatorNodeRef: on the
  // row they would swallow the title click and the 수정/삭제 buttons, and the
  // keyboard sensor only starts when the focused element is the activator.
  const handle = (
    <button
      type="button"
      ref={setActivatorNodeRef}
      {...attributes}
      {...listeners}
      aria-label={`${score.title} 순서 바꾸기`}
      className="flex touch-none cursor-grab select-none items-center px-1 text-stone-400 hover:text-stone-600"
    >
      <GripVertical className="h-[18px] w-[18px]" aria-hidden="true" />
    </button>
  );

  return (
    <ScoreRow
      score={score}
      index={index}
      canManage
      onUpdate={onUpdate}
      onDelete={onDelete}
      handle={handle}
      rowProps={{
        ref: setNodeRef,
        style: { transform: CSS.Transform.toString(transform), transition },
      }}
    />
  );
}

function SortableRows({ rows, locked, onDragEnd, onUpdate, onDelete }) {
  // Mouse and touch get different activation rules, so they are two sensors:
  // a sensor takes one constraint. Distance keeps a click on the handle a
  // click; the touch delay lets a swipe still scroll the page. Both values are
  // untested on a real device.
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      <SortableContext items={rows.map((row) => row.id)} strategy={verticalListSortingStrategy}>
        {rows.map((score, index) => (
          <SortableScoreRow
            key={score.id}
            score={score}
            index={index}
            locked={locked}
            onUpdate={onUpdate}
            onDelete={onDelete}
          />
        ))}
      </SortableContext>
    </DndContext>
  );
}

export default function StageCard({
  scores,
  weekOf,
  onUpdate,
  onDelete,
  canManage = true,
  onReorder,
  isReordering = false,
}) {
  // The order just dropped, tied to the `scores` array it was dropped on.
  // Compared by reference while rendering, with no effect: once the hook
  // re-reads the list the prop is a new array and the server's order wins by
  // itself; if the re-read failed the prop is the same array and the order the
  // server just saved stays on screen.
  const [pending, setPending] = useState(null);
  const [isSaving, setIsSaving] = useState(false);

  const weekScores = orderScoresBy(scores, pending && pending.base === scores ? pending.ids : null);
  const stageScores = weekScores.slice(0, VISIBLE_COUNT);
  const reorderable = canManage && typeof onReorder === "function";
  const locked = isReordering || isSaving;

  const handleDragEnd = async ({ active, over }) => {
    if (locked) return;
    const next = reorderStage(
      weekScores.map((score) => score.id),
      stageScores.length,
      active.id,
      over ? over.id : null
    );
    if (next === null) return;

    setPending({ ids: next, base: scores });
    setIsSaving(true);
    let result = { saved: false };
    try {
      result = await onReorder(next);
    } catch {
      // Treated as not saved: showing the dropped order would claim a write
      // that never happened.
    }
    if (!result || !result.saved) setPending(null);
    setIsSaving(false);
  };

  return (
    <Card>
      {/* No 발행 here: it is a button with no onClick in the old card, and
          status is written 'draft' at creation and never changed, so there is
          nothing for it to call. Reordering is the drag handle below, which
          PATCHes the week's conti order. */}
      <CardHeader>
        <CardTitle>콘티</CardTitle>
        <div className="mt-1 flex items-center justify-between gap-2">
          <p className="text-xs text-stone-500">{weekOf} (돌아오는 일요일)</p>
          {/* A member reads the week and changes nothing: the server refuses
              every write and the conti screen itself, so none of the ways in
              are drawn for them. */}
          {canManage ? (
            <Button variant="outline" size="sm" type="button" asChild>
              <Link to={`/conti/${weekOf}`}>콘티 편집</Link>
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {stageScores.length === 0 ? (
          <div className="rounded-md border border-dashed border-stone-300 p-4 text-sm text-stone-500">
            돌아오는 일요일 주차의 악보가 없습니다.
          </div>
        ) : reorderable ? (
          <SortableRows
            rows={stageScores}
            locked={locked}
            onDragEnd={handleDragEnd}
            onUpdate={onUpdate}
            onDelete={onDelete}
          />
        ) : (
          stageScores.map((score, index) => (
            <ScoreRow
              key={score.id}
              score={score}
              index={index}
              canManage={canManage}
              onUpdate={onUpdate}
              onDelete={onDelete}
            />
          ))
        )}
      </CardContent>
    </Card>
  );
}
