"use client";

// Form controls for the Learn widgets. Values are clamped, so a simulator never gets NaN.

import { useEffect, useId, useState } from "react";

export function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  hint,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step?: number;
  hint?: string;
}) {
  const id = useId();
  // Local text so a half-typed value ("-", "0.") is not clamped away; valid in-range values apply at once.
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  const typed = Number(text);
  const outOfRange = text !== "" && Number.isFinite(typed) && (typed < min || typed > max);
  return (
    <label htmlFor={id} title={hint}>
      {label}
      <input
        id={id}
        type="number"
        inputMode="decimal"
        value={text}
        min={min}
        max={max}
        step={step}
        onChange={(e) => {
          setText(e.target.value);
          const v = Number(e.target.value);
          // Out-of-range values apply clamped at once; the text stays as typed, with a note below.
          if (e.target.value !== "" && Number.isFinite(v)) onChange(Math.min(max, Math.max(min, v)));
        }}
        onBlur={() => {
          const v = Number(text);
          const next = text !== "" && Number.isFinite(v) ? Math.min(max, Math.max(min, v)) : value;
          setText(String(next));
          if (next !== value) onChange(next);
        }}
        aria-invalid={outOfRange || undefined}
      />
      {outOfRange && (
        <span className="muted small" role="status" style={{ display: "block" }}>
          Allowed {min} to {max}; using {Math.min(max, Math.max(min, typed))}.
        </span>
      )}
    </label>
  );
}

export function RangeField({
  label,
  value,
  onChange,
  min,
  max,
  step,
  format,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step: number;
  format: (v: number) => string;
}) {
  const id = useId();
  return (
    <label htmlFor={id}>
      {label}: <strong>{format(value)}</strong>
      <input id={id} type="range" value={value} min={min} max={max} step={step} onChange={(e) => onChange(Number(e.target.value))} aria-valuetext={format(value)} />
    </label>
  );
}

export function SeedField({ seed, onChange }: { seed: number; onChange: (v: number) => void }) {
  const id = useId();
  return (
    <>
      <label htmlFor={id} title="Same seed, same random numbers: the result is reproducible.">
        Seed
        <input
          id={id}
          type="number"
          value={seed}
          min={1}
          max={2 ** 31 - 1}
          step={1}
          onChange={(e) => {
            const v = Math.floor(Number(e.target.value));
            if (Number.isFinite(v) && v >= 1) onChange(v);
          }}
        />
      </label>
      <button type="button" onClick={() => onChange((seed % 2147483646) + 1)}>
        New seed
      </button>
    </>
  );
}
