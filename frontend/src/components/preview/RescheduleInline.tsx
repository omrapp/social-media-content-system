import { useState } from "react";
import { RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

export function RescheduleInline({ postId, onDone }: { postId: string; onDone: () => void }) {
  const [val, setVal] = useState("");
  const [saving, setSaving] = useState(false);
  const doSave = async () => {
    if (!val) return;
    setSaving(true);
    try {
      await api.post(`/posts/${postId}/reschedule`, { scheduled_at: new Date(val).toISOString() });
      toast.success("Rescheduled");
      setVal("");
      onDone();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Reschedule failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex gap-2">
      <input
        type="datetime-local"
        value={val}
        onChange={(e) => setVal(e.target.value)}
        className="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs"
      />
      <button
        disabled={!val || saving}
        onClick={doSave}
        className="flex items-center gap-1 px-3 py-1 text-xs rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-40"
      >
        <RotateCcw size={11} /> Set
      </button>
    </div>
  );
}
