import Link from "next/link";
import { PageHeader } from "@/components/Card";
import { SessionList } from "@/features/dashboard/SessionList";

export default function DashboardPage() {
  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Past and in-flight research sessions."
        actions={
          <Link
            href="/new"
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500"
          >
            New Research
          </Link>
        }
      />
      <SessionList />
    </div>
  );
}
