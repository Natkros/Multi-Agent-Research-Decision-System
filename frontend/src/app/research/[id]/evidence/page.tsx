import { EvidenceExplorer } from "@/features/evidence-explorer/EvidenceExplorer";

export default async function EvidencePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EvidenceExplorer researchId={id} />;
}
