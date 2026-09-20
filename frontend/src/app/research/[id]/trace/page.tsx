import { AgentTraceView } from "@/features/agent-trace/AgentTraceView";

export default function TracePage({ params }: { params: { id: string } }) {
  return <AgentTraceView researchId={params.id} />;
}
