# Chat Mode

Enable and use chat mode in the Echo AI system for natural language interactions.

## What is Chat Mode?

Chat Mode allows users to interact with the AI system using natural language prompts. Instead of structured API calls, users can type free-form messages and receive intelligent, context-aware responses.

## How to Enable Chat Mode

1. Start the Echo AI service with the --chat-mode flag:

bash
   echo-ai serve --chat-mode


2. Or enable it via the API endpoint:

http
   POST /api/v1/chat
   {
     "prompt": "Hello, how are you?",
     "session_id": "user_123"
   }


3. The system will respond with a natural language reply, maintaining context across turns.

## Features

- Context-aware conversation history
- Dynamic response generation
- Support for multi-turn dialogues
- Real-time feedback on user intent

## Example Interaction

> User: "What’s the weather like today?"
> AI: "It's sunny with a high of 24°C. Perfect for a walk!"

> User: "Can you recommend a book?"
> AI: "Sure! I recommend The Midnight Library by Matt Haig — it’s a beautiful story about second chances."

## Next Steps

- Explore the /api/v1/chat endpoint in the API docs.
- Try using chat mode in the CLI with echo-ai chat.
- Feedback? Submit suggestions at feedback.echotek.ai.

---

> 📝 This page was generated automatically by the Echo AI documentation system.


---

## ✅ Where to Place It

### 📁 Final Path:
docs/chat_mode.md


> ✅ This means:
> Create a file named chat_mode.md in the docs/ directory of your project.

### 📂 Project Structure Example:
your-project/
├── docs/
│   └── chat_mode.md        ← ✅ Place this file here
├── mkdocs.yml
├── ...


> 🔍 Make sure your docs/ folder is at the root of your project (same level as mkdocs.yml).
