import type { Metadata } from "next";
import { AuthGate } from "@/components/AuthGate";
import { NavSidebar } from "@/components/NavSidebar";
import "./globals.css";

export const metadata: Metadata = {
  title: "Multi-Agent Research & Decision System",
  description: "Research sessions, evidence, decisions, and agent trace for the multi-agent research pipeline.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-surface">
        <AuthGate>
          <div className="flex min-h-screen">
            <NavSidebar />
            <main className="min-w-0 flex-1 p-6">{children}</main>
          </div>
        </AuthGate>
      </body>
    </html>
  );
}
