import type { ChatMessage } from '@/types/chat'
export function ResearchReportCard({ message }: { message: ChatMessage }) {
  return <div data-testid={`report-msg-${message.id}`}>report: {message.research_report_summary ?? ''}</div>
}
