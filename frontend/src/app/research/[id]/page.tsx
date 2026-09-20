import { ActiveResearchView } from "@/features/active-research/ActiveResearchView";

export default async function ResearchOverviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ActiveResearchView researchId={id} />;
}
