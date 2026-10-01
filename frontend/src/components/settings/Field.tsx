import type { FieldHint } from "./types";
import { FIELD_HINTS, FIELD_OPTIONS } from "./constants";

export function FieldHintText({ hint }: { hint?: FieldHint }) {
  if (!hint) return null;
  return (
    <div className="mt-1 space-y-0.5">
      <p className="text-xs text-gray-500 leading-relaxed">
        {hint.desc}
        {hint.example && (
          <span className="ml-1 text-gray-600">
            e.g. <code className="font-mono text-gray-500">{hint.example}</code>
          </span>
        )}
      </p>
      {hint.recommended !== undefined && (
        <p className="text-xs text-emerald-400/80 font-medium">
          ✦ Recommended: <span className="font-mono text-emerald-300">{hint.recommended}</span>
        </p>
      )}
    </div>
  );
}

export function Field({
  group,
  label,
  value,
  original,
  onChange,
}: {
  group?: string;
  label: string;
  value: unknown;
  original: unknown;
  onChange: (v: unknown) => void;
}) {
  const dirty = JSON.stringify(value) !== JSON.stringify(original);
  const displayLabel = label.replace(/_/g, " ");
  const hint = group ? FIELD_HINTS[`${group}.${label}`] : undefined;

  if (typeof original === "boolean") {
    return (
      <div className="py-1">
        <div className="flex items-center justify-between">
          <span className="text-sm text-gray-300 capitalize">{displayLabel}</span>
          <button
            role="switch"
            aria-checked={Boolean(value)}
            onClick={() => onChange(!value)}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
              Boolean(value) ? "bg-blue-600" : "bg-gray-700"
            }`}
          >
            <span
              className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${
                Boolean(value) ? "translate-x-4" : "translate-x-1"
              }`}
            />
          </button>
        </div>
        <FieldHintText hint={hint} />
      </div>
    );
  }

  if (typeof original === "number") {
    return (
      <div className="py-1">
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm text-gray-300 capitalize">{displayLabel}</span>
          <input
            type="number"
            value={Number(value ?? 0)}
            onChange={(e) => onChange(Number(e.target.value))}
            className={`w-28 bg-gray-800 border rounded-lg px-3 py-1.5 text-sm text-right tabular-nums transition-colors ${
              dirty ? "border-amber-500 text-amber-200" : "border-gray-700 text-gray-200"
            }`}
          />
        </div>
        <FieldHintText hint={hint} />
      </div>
    );
  }

  if (Array.isArray(original)) {
    return (
      <div className="py-1">
        <label className="block text-sm text-gray-300 capitalize mb-1.5">{displayLabel}</label>
        <input
          type="text"
          value={(value as unknown[] | undefined)?.join(", ") ?? ""}
          onChange={(e) =>
            onChange(
              e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean)
            )
          }
          className={`w-full bg-gray-800 border rounded-lg px-3 py-1.5 text-sm transition-colors ${
            dirty ? "border-amber-500 text-amber-200" : "border-gray-700 text-gray-200"
          }`}
          placeholder="comma, separated, values"
        />
        <FieldHintText hint={hint} />
      </div>
    );
  }

  if (typeof original === "object" && original !== null) {
    return (
      <div className="py-1">
        <span className="block text-sm text-gray-300 capitalize mb-1.5">{displayLabel}</span>
        <div className="pl-3 border-l-2 border-gray-700 space-y-2">
          {Object.entries(original as Record<string, unknown>).map(([subKey, subVal]) => (
            <Field
              key={subKey}
              group={group}
              label={subKey}
              value={(value as Record<string, unknown>)?.[subKey] ?? subVal}
              original={subVal}
              onChange={(next) =>
                onChange({ ...(value as Record<string, unknown>), [subKey]: next })
              }
            />
          ))}
        </div>
      </div>
    );
  }

  // Known enum string field → dropdown (prevents invalid free-text values).
  const options = group ? FIELD_OPTIONS[`${group}.${label}`] : undefined;
  if (options && typeof original === "string") {
    return (
      <div className="py-1">
        <label className="block text-sm text-gray-300 capitalize mb-1.5">{displayLabel}</label>
        <select
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          className={`w-full bg-gray-800 border rounded-lg px-3 py-1.5 text-sm cursor-pointer transition-colors focus:border-blue-500 focus:outline-none ${
            dirty ? "border-amber-500 text-amber-200" : "border-gray-700 text-gray-200"
          }`}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <FieldHintText hint={hint} />
      </div>
    );
  }

  return (
    <div className="py-1">
      <label className="block text-sm text-gray-300 capitalize mb-1.5">{displayLabel}</label>
      <input
        type="text"
        value={String(value ?? "")}
        onChange={(e) => onChange(e.target.value)}
        className={`w-full bg-gray-800 border rounded-lg px-3 py-1.5 text-sm transition-colors ${
          dirty ? "border-amber-500 text-amber-200" : "border-gray-700 text-gray-200"
        }`}
      />
      <FieldHintText hint={hint} />
    </div>
  );
}
