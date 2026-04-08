import { memo, useState, type KeyboardEvent, type FormEvent } from 'react';
import { useChat } from '../context';

interface ChatInputProps {
  placeholder?: string;
}

export const ChatInput = memo(function ChatInput({
  placeholder = 'Type your message...',
}: ChatInputProps) {
  const { sendMessage, isConnected, isStreaming, stopGeneration } = useChat();
  const [input, setInput] = useState('');

  const disabled = !isConnected;
  const placeholderText = isStreaming ? 'Generating...' : placeholder;

  const handleSend = () => {
    const trimmed = input.trim();
    if (trimmed && !disabled) {
      sendMessage(trimmed);
      setInput('');
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    handleSend();
  };

  return (
    <form className="chat-input-container" onSubmit={handleSubmit}>
      <div className="input-wrapper">
        <textarea
          id="chat-input"
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholderText}
          disabled={disabled || isStreaming}
          rows={1}
        />
        {isStreaming ? (
          <button
            type="button"
            className="stop-button"
            onClick={stopGeneration}
            title="Stop generation"
          >
            <span>⏹</span>
          </button>
        ) : (
          <button type="submit" className="send-button" disabled={disabled || !input.trim()}>
            <span>Send</span>
          </button>
        )}
      </div>
    </form>
  );
});
