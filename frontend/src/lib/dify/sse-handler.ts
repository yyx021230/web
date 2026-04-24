export interface SSEEvent {
  event: string;
  data: Record<string, unknown>;
}

export type SSECallback = {
  onWorkflowStarted?: (data: Record<string, unknown>) => void;
  onNodeStarted?: (data: Record<string, unknown>) => void;
  onNodeFinished?: (data: Record<string, unknown>) => void;
  onWorkflowFinished?: (data: Record<string, unknown>) => void;
  onTextChunk?: (text: string) => void;
  onError?: (error: string) => void;
  onCompleted?: () => void;
};

export function handleSSEStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  callbacks: SSECallback
): void {
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  async function read() {
    try {
      const result = await reader.read();
      if (result.done) {
        callbacks.onCompleted?.();
        return;
      }

      buffer += decoder.decode(result.value, { stream: true });
      const lines = buffer.split('\n');

      lines.forEach((message) => {
        if (message.startsWith('data: ')) {
          try {
            const data = JSON.parse(message.substring(6));
            processEvent(data, callbacks);
          } catch {
            // Ignore malformed JSON
          }
        }
      });

      buffer = lines[lines.length - 1] || '';
      read();
    } catch (error) {
      callbacks.onError?.(String(error));
    }
  }

  read();
}

function processEvent(data: Record<string, unknown>, callbacks: SSECallback): void {
  const event = data.event as string;

  switch (event) {
    case 'workflow_started':
      callbacks.onWorkflowStarted?.(data);
      break;
    case 'node_started':
      callbacks.onNodeStarted?.(data);
      break;
    case 'node_finished':
      callbacks.onNodeFinished?.(data);
      break;
    case 'workflow_finished':
      callbacks.onWorkflowFinished?.(data);
      break;
    case 'message':
      callbacks.onTextChunk?.(String(data.answer || ''));
      break;
    default:
      console.warn(`Unknown SSE event: ${event}`, data);
  }
}
