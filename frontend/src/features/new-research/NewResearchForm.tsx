"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { ResearchMode } from "@/types";
import { Card } from "@/components/Card";

function ListField({
  label,
  placeholder,
  values,
  onChange,
}: {
  label: string;
  placeholder: string;
  values: string[];
  onChange: (values: string[]) => void;
}) {
  const [draft, setDraft] = useState("");

  const add = () => {
    const trimmed = draft.trim();
    if (!trimmed) return;
    onChange([...values, trimmed]);
    setDraft("");
  };

  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-slate-300">{label}</label>
      <div className="flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder={placeholder}
          className="flex-1 rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-blue-500 focus:outline-none"
        />
        <button
          type="button"
          onClick={add}
          className="rounded-md border border-surface-border px-3 py-2 text-sm text-slate-300 hover:bg-surface-border"
        >
          Add
        </button>
      </div>
      {values.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-2">
          {values.map((v, i) => (
            <li
              key={`${v}-${i}`}
              className="flex items-center gap-1 rounded-full border border-surface-border bg-surface px-2.5 py-1 text-xs text-slate-300"
            >
              {v}
              <button
                type="button"
                onClick={() => onChange(values.filter((_, idx) => idx !== i))}
                className="text-slate-500 hover:text-red-400"
                aria-label={`Remove ${v}`}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function NewResearchForm() {
  const router = useRouter();
  const [question, setQuestion] = useState("");
  const [constraints, setConstraints] = useState<string[]>([]);
  const [alternatives, setAlternatives] = useState<string[]>([]);
  const [criteria, setCriteria] = useState<string[]>([]);
  const [mode, setMode] = useState<ResearchMode>("auto");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!question.trim()) {
      setError("A research question is required.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.createResearch({
        question: question.trim(),
        constraints,
        alternatives,
        criteria,
        mode,
      });
      router.push(`/research/${result.research_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to submit research request.");
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="max-w-2xl space-y-6">
      <Card title="Research Question">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={3}
          required
          placeholder="e.g. Should a startup build its own vector database or use a managed service?"
          className="w-full resize-none rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-blue-500 focus:outline-none"
        />
      </Card>

      <Card title="Mode">
        <div className="flex gap-2">
          {(["auto", "assisted", "manual"] as ResearchMode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`rounded-md border px-3 py-2 text-sm capitalize ${
                mode === m
                  ? "border-blue-500 bg-blue-500/10 text-blue-300"
                  : "border-surface-border text-slate-400 hover:bg-surface-border"
              }`}
            >
              {m}
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-slate-500">
          {mode === "auto" && "Runs end-to-end with no pauses."}
          {mode === "assisted" && "Pauses at key checkpoints for approval (requires the /approve endpoint)."}
          {mode === "manual" && "Pauses more frequently for human review."}
        </p>
      </Card>

      <Card title="Optional Hints">
        <div className="space-y-4">
          <ListField
            label="Constraints"
            placeholder="e.g. budget < $5k/mo"
            values={constraints}
            onChange={setConstraints}
          />
          <ListField
            label="Alternatives"
            placeholder="e.g. Managed Qdrant"
            values={alternatives}
            onChange={setAlternatives}
          />
          <ListField
            label="Criteria"
            placeholder="e.g. operational burden"
            values={criteria}
            onChange={setCriteria}
          />
        </div>
      </Card>

      {error && (
        <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="rounded-md bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
      >
        {submitting ? "Submitting..." : "Start Research"}
      </button>
    </form>
  );
}
