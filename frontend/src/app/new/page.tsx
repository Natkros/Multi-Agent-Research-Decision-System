import { PageHeader } from "@/components/Card";
import { NewResearchForm } from "@/features/new-research/NewResearchForm";

export default function NewResearchPage() {
  return (
    <div>
      <PageHeader title="New Research" description="Submit a question for the multi-agent pipeline to research." />
      <NewResearchForm />
    </div>
  );
}
