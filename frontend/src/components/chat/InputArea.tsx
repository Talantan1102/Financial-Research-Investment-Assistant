interface InputAreaProps {
  sessionId?: string
}

export function InputArea({ sessionId }: InputAreaProps) {
  return (
    <div data-testid="input-area" style={{ padding: 12, borderTop: '1px solid #eee' }}>
      <input type="text" placeholder="Type a message…" disabled={!sessionId} style={{ width: '100%' }} />
    </div>
  )
}
