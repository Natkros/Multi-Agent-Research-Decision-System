import { EvidenceExplorer } from "@/features/evidence-explorer/EvidenceExplorer";

export default function EvidencePage({ params }: { params: { id: string } }) {
  return <EvidenceExplorer researchId={params.id} />;
}
