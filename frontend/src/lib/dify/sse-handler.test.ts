import { describe, expect, it, vi } from 'vitest';

import { handleSSEStream } from './sse-handler';

function readerFromChunks(chunks: Array<string | Error>) {
  const encoder = new TextEncoder();
  let index = 0;
  return {
    read: vi.fn(async () => {
      const item = chunks[index++];
      if (item instanceof Error) throw item;
      if (item === undefined) return { done: true, value: undefined };
      return { done: false, value: encoder.encode(item) };
    }),
  } as unknown as ReadableStreamDefaultReader<Uint8Array>;
}

describe('handleSSEStream', () => {
  it('processes fragmented workflow events and ignores malformed JSON', async () => {
    const callbacks = {
      onWorkflowStarted: vi.fn(),
      onNodeStarted: vi.fn(),
      onNodeFinished: vi.fn(),
      onWorkflowFinished: vi.fn(),
      onTextChunk: vi.fn(),
      onCompleted: vi.fn(),
    };
    const reader = readerFromChunks([
      'data: {"event":"workflow_started","id":1}\ndata: {bad}\ndata: {"event":"node_started"',
      '}\ndata: {"event":"node_finished"}\ndata: {"event":"message","answer":"完成一半"}\n',
      'data: {"event":"workflow_finished"}\n',
    ]);

    handleSSEStream(reader, callbacks);
    await vi.waitFor(() => expect(callbacks.onCompleted).toHaveBeenCalledOnce());
    expect(callbacks.onWorkflowStarted).toHaveBeenCalledOnce();
    expect(callbacks.onNodeStarted).toHaveBeenCalledOnce();
    expect(callbacks.onNodeFinished).toHaveBeenCalledOnce();
    expect(callbacks.onWorkflowFinished).toHaveBeenCalledOnce();
    expect(callbacks.onTextChunk).toHaveBeenCalledWith('完成一半');
  });

  it('reports reader errors without completing', async () => {
    const onError = vi.fn();
    const onCompleted = vi.fn();
    handleSSEStream(readerFromChunks([new Error('network closed')]), { onError, onCompleted });
    await vi.waitFor(() => expect(onError).toHaveBeenCalledWith('Error: network closed'));
    expect(onCompleted).not.toHaveBeenCalled();
  });

  it('warns for unknown events', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const onCompleted = vi.fn();
    handleSSEStream(readerFromChunks(['data: {"event":"custom"}\n']), { onCompleted });
    await vi.waitFor(() => expect(onCompleted).toHaveBeenCalledOnce());
    expect(warn).toHaveBeenCalledWith('Unknown SSE event: custom', { event: 'custom' });
  });
});
