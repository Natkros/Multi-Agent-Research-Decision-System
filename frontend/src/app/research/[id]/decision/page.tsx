import { DecisionMatrixView } from "@/features/decision-matrix/DecisionMatrixView";

export default function DecisionPage({ params }: { params: { id: string } }) {
  return <DecisionMatrixView researchId={params.id} />;
}
