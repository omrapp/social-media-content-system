import { KeyRound, CheckCircle2, XCircle } from "lucide-react";

export function SecretsStatus({ secrets }: { secrets: Record<string, boolean> }) {
  const entries = Object.entries(secrets);
  if (entries.length === 0) return null;
  const missing = entries.filter(([, set]) => !set);

  return (
    <section className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <KeyRound size={14} className="text-gray-400" />
          <h3 className="text-sm font-semibold text-gray-300">Environment secrets</h3>
        </div>
        {missing.length === 0 ? (
          <span className="text-xs text-green-400 flex items-center gap-1">
            <CheckCircle2 size={12} /> All set
          </span>
        ) : (
          <span className="text-xs text-red-400 flex items-center gap-1">
            <XCircle size={12} /> {missing.length} missing
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-y-2 gap-x-4">
        {entries.map(([key, set]) => (
          <div key={key} className="flex items-center gap-2">
            <span className={`inline-block w-1.5 h-1.5 rounded-full shrink-0 ${set ? "bg-green-500" : "bg-red-500"}`} />
            <code className="text-xs text-gray-400 truncate">{key}</code>
            <span className={`text-xs ml-auto shrink-0 ${set ? "text-green-400" : "text-red-400"}`}>
              {set ? "set" : "missing"}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
