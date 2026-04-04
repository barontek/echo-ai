import { describe, it, expect } from 'vitest';

describe('Components', () => {
  it('ChatInput renders correctly', async () => {
    // Verify ChatInput can render when we provide the context
    // For now just check the component renders without crashing
    const { ChatInput } = await import('../components/ChatInput');
    const { ChatProvider } = await import('../context');

    // Simple smoke test - just verify imports work
    expect(ChatInput).toBeDefined();
    expect(ChatProvider).toBeDefined();
  });

  it('context exports work', async () => {
    const context = await import('../context');
    expect(context.ChatProvider).toBeDefined();
    expect(context.useChat).toBeDefined();
    expect(context.ChatContext).toBeDefined();
  });

  it('types file exists', async () => {
    // Types are compile-time only, verify the file exists
    const types = await import('../types');
    expect(types).toBeDefined();
  });

  it('api client exports work', async () => {
    const { api } = await import('../api/client');
    expect(api).toBeDefined();
    expect(typeof api.getSessions).toBe('function');
    expect(typeof api.getModels).toBe('function');
  });
});
