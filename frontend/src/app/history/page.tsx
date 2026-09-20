import { PageHeader } from "@/components/Card";
import { SessionList } from "@/features/dashboard/SessionList";

/**
 * Stub-plus: research history is currently the same "all sessions" list as
 * the Dashboard (GET /research has no additional filtering/search on the
 * backend yet). A dedicated history page with date-range/search filters was
 * out of scope for this pass -- noted as incomplete per the brief's
 * priority order (pages 1-8 first).
 */
export default function HistoryPage() {
  return (
    <div>
      <PageHeader
        title="Research History"
        description="All past research sessions. (Stub: reuses the Dashboard list; search/date filters not yet implemented.)"
      />
      <SessionList />
    </div>
  );
}
