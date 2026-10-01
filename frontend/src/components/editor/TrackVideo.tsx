/**
 * Video track — the row of cuts, reorderable (dnd-kit) and trimmable.
 *
 * Trim drags are LOCAL until pointerup, then committed once. Committing on
 * every pointermove would push ~60 entries/second into the undo ring and make
 * ctrl-Z useless.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  horizontalListSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Copy, Scissors, Trash2 } from "lucide-react";

import { MIN_CUT_S, cutDuration, type Cut, type ProxyMap } from "@/types/editor";

export interface TrackVideoProps {
  cuts: Cut[];
  pxPerSecond: number;
  selectedCutId: string | null;
  proxies: ProxyMap;
  onSelect: (id: string) => void;
  onReorder: (from: number, to: number) => void;
  onTrim: (id: string, inS: number, outS: number) => void;
  onSplit: (id: string) => void;
  onDelete: (id: string) => void;
  onDuplicate: (id: string) => void;
}

interface TrimDraft {
  id: string;
  edge: "start" | "end";
  in_s: number;
  out_s: number;
}

function ClipBody({
  cut, index, widthPx, selected, hasProxy, onSelect,
  onTrimStart, onSplit, onDelete, onDuplicate,
}: {
  cut: Cut;
  index: number;
  widthPx: number;
  selected: boolean;
  hasProxy: boolean;
  onSelect: () => void;
  onTrimStart: (edge: "start" | "end", clientX: number) => void;
  onSplit: () => void;
  onDelete: () => void;
  onDuplicate: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: cut.id });

  return (
    <div
      ref={setNodeRef}
      style={{
        width: widthPx,
        transform: CSS.Translate.toString(transform),
        transition,
        opacity: isDragging ? 0.6 : 1,
      }}
      className={`relative h-16 shrink-0 rounded-md overflow-hidden select-none
        ${selected ? "ring-2 ring-indigo-400" : "ring-1 ring-white/10"}
        ${hasProxy ? "bg-gray-800" : "bg-gray-800/60"}`}
      onClick={onSelect}
    >
      <div
        {...attributes}
        {...listeners}
        className="absolute inset-0 cursor-grab active:cursor-grabbing px-2 py-1"
        title={`Clip ${index + 1} · ${cutDuration(cut).toFixed(2)}s`}
      >
        <div className="text-[10px] font-medium text-gray-300 truncate">
          {index + 1}. {cut.src_media_id}
        </div>
        <div className="text-[10px] text-gray-500">
          {cutDuration(cut).toFixed(1)}s
          {cut.speed !== 1 && <span className="text-amber-400"> · {cut.speed.toFixed(2)}×</span>}
          {cut.ken_burns?.enabled && <span className="text-sky-400"> · KB</span>}
        </div>
        {!hasProxy && (
          <div className="absolute bottom-1 left-2 text-[9px] text-gray-500">preparing…</div>
        )}
      </div>

      {/* Trim handles — pointerdown is swallowed so dnd-kit never sees it. */}
      {(["start", "end"] as const).map((edge) => (
        <div
          key={edge}
          onPointerDown={(e) => {
            e.stopPropagation();
            e.preventDefault();
            onTrimStart(edge, e.clientX);
          }}
          className={`absolute top-0 bottom-0 w-2 cursor-ew-resize bg-indigo-400/0
                      hover:bg-indigo-400/70 ${edge === "start" ? "left-0" : "right-0"}`}
        />
      ))}

      {selected && (
        <div className="absolute top-1 right-1 flex gap-0.5">
          <button onClick={(e) => { e.stopPropagation(); onSplit(); }}
            title="Split at playhead (S)"
            className="p-1 rounded bg-gray-900/80 hover:bg-gray-700 text-gray-300">
            <Scissors className="w-3 h-3" />
          </button>
          <button onClick={(e) => { e.stopPropagation(); onDuplicate(); }}
            title="Duplicate"
            className="p-1 rounded bg-gray-900/80 hover:bg-gray-700 text-gray-300">
            <Copy className="w-3 h-3" />
          </button>
          <button onClick={(e) => { e.stopPropagation(); onDelete(); }}
            title="Delete (Del)"
            className="p-1 rounded bg-gray-900/80 hover:bg-rose-600 text-gray-300">
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      )}
    </div>
  );
}

export function TrackVideo({
  cuts, pxPerSecond, selectedCutId, proxies,
  onSelect, onReorder, onTrim, onSplit, onDelete, onDuplicate,
}: TrackVideoProps) {
  const [draft, setDraft] = useState<TrimDraft | null>(null);
  const dragRef = useRef<{ startX: number; base: TrimDraft } | null>(null);

  // 4px of travel before a drag starts, so a plain click still selects.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  const beginTrim = useCallback((cut: Cut, edge: "start" | "end", clientX: number) => {
    const base: TrimDraft = { id: cut.id, edge, in_s: cut.in_s, out_s: cut.out_s };
    dragRef.current = { startX: clientX, base };
    setDraft(base);
  }, []);

  useEffect(() => {
    if (!draft) return;
    const move = (e: PointerEvent) => {
      const d = dragRef.current;
      if (!d) return;
      const deltaS = (e.clientX - d.startX) / pxPerSecond;
      if (d.base.edge === "start") {
        const nextIn = Math.min(d.base.out_s - MIN_CUT_S, Math.max(0, d.base.in_s + deltaS));
        setDraft({ ...d.base, in_s: nextIn });
      } else {
        // No upper bound client-side: the source clip's true length is not in
        // the EDL. compile() clamps against the probed duration on export.
        const nextOut = Math.max(d.base.in_s + MIN_CUT_S, d.base.out_s + deltaS);
        setDraft({ ...d.base, out_s: nextOut });
      }
    };
    const up = () => {
      setDraft((cur) => {
        if (cur) onTrim(cur.id, cur.in_s, cur.out_s);
        return null;
      });
      dragRef.current = null;
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [draft, onTrim, pxPerSecond]);

  const handleDragEnd = (e: DragEndEvent) => {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    const from = cuts.findIndex((c) => c.id === active.id);
    const to = cuts.findIndex((c) => c.id === over.id);
    if (from >= 0 && to >= 0) onReorder(from, to);
  };

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <SortableContext items={cuts.map((c) => c.id)} strategy={horizontalListSortingStrategy}>
        <div className="flex gap-px items-center h-16">
          {cuts.map((cut, index) => {
            // While a trim drag is live the clip is drawn from the draft, which
            // is not yet committed to the EDL.
            const live: Cut = draft?.id === cut.id
              ? { ...cut, in_s: draft.in_s, out_s: draft.out_s }
              : cut;
            return (
              <ClipBody
                key={cut.id}
                cut={live}
                index={index}
                widthPx={Math.max(24, cutDuration(live) * pxPerSecond)}
                selected={selectedCutId === cut.id}
                hasProxy={Boolean(proxies[cut.id])}
                onSelect={() => onSelect(cut.id)}
                onTrimStart={(edge, clientX) => beginTrim(cut, edge, clientX)}
                onSplit={() => onSplit(cut.id)}
                onDelete={() => onDelete(cut.id)}
                onDuplicate={() => onDuplicate(cut.id)}
              />
            );
          })}
        </div>
      </SortableContext>
    </DndContext>
  );
}
