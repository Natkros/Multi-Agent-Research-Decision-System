import { ActiveResearchView } from "@/features/active-research/ActiveResearchView";

export default function ResearchOverviewPage({ params }: { params: { id: string } }) {
  return <ActiveResearchView researchId={params.id} />;
}
