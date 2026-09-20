import { ReportView } from "@/features/report/ReportView";

export default function ReportPage({ params }: { params: { id: string } }) {
  return <ReportView researchId={params.id} />;
}
