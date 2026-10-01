import { Clock, Plus, X } from "lucide-react";
import { FieldHintText } from "./Field";
import type { FieldHint } from "./types";

export function TimeSlotField({
  value,
  original,
  hint,
  onChange,
}: {
  value: unknown;
  original: unknown;
  hint?: FieldHint;
  onChange: (v: unknown) => void;
}) {
  const slots = ((value ?? original) as string[]) ?? [];
  const dirty = JSON.stringify(value) !== JSON.stringify(original);

  const update = (idx: number, t: string) => {
    const next = [...slots];
    next[idx] = t;
    onChange(next.sort());
  };

  const remove = (idx: number) => onChange(slots.filter((_, i) => i !== idx));

  const add = () => onChange([...slots, "12:00"].sort());

  return (
    <div className="py-1">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-sm text-gray-300">Daily slots</span>
        <button
          onClick={add}
          className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 px-2 py-1 rounded-lg bg-blue-500/10 hover:bg-blue-500/20 transition-colors"
        >
          <Plus size={11} /> Add slot
        </button>
      </div>

      {slots.length === 0 && (
        <p className="text-xs text-gray-600 py-2 text-center border border-dashed border-gray-700 rounded-lg">
          No slots — add at least one.
        </p>
      )}

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {slots.map((slot, idx) => (
          <div
            key={idx}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border transition-colors ${
              dirty ? "border-amber-500/60 bg-amber-500/5" : "border-gray-700 bg-gray-800"
            }`}
          >
            <Clock size={12} className="text-gray-500 shrink-0" />
            <input
              type="time"
              value={slot}
              onChange={(e) => update(idx, e.target.value)}
              className="flex-1 bg-transparent text-sm tabular-nums text-gray-200 outline-none min-w-0"
            />
            <button
              onClick={() => remove(idx)}
              disabled={slots.length <= 1}
              className="text-gray-600 hover:text-red-400 transition-colors disabled:opacity-20 disabled:cursor-not-allowed shrink-0"
            >
              <X size={12} />
            </button>
          </div>
        ))}
      </div>
      <FieldHintText hint={hint} />
    </div>
  );
}
