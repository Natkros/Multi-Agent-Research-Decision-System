import { Card, PageHeader } from "@/components/Card";

/**
 * Stub page. The backend has no settings/config endpoints yet (Phase 8
 * security/auth and model-routing config live server-side only), so this
 * just surfaces the read-only values the frontend itself knows about.
 */
export default function SettingsPage() {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
  return (
    <div>
      <PageHeader title="System Settings" description="Stub page -- no backend settings endpoints exist yet." />
      <Card title="Frontend Configuration">
        <dl className="space-y-2 text-sm">
          <div className="flex justify-between border-b border-surface-border/60 py-2">
            <dt className="text-slate-500">API Base URL</dt>
            <dd className="font-mono text-slate-300">{apiUrl}</dd>
          </div>
        </dl>
      </Card>
    </div>
  );
}
