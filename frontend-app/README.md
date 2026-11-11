# Frontend Application

The **Frontend Application** is a modern, responsive web dashboard for the Enterprise Omnichannel AI Support Hub. It provides a real-time conversational interface to the LangGraph AI Support Agent with streaming responses, MCP tool execution visibility, and live order tracking.

---

## 🚀 Features

1. **Omnichannel Chat Interface**: Real-time interaction with the AI support system with Server-Sent Events (SSE) streaming.
2. **Tool Execution Badges**: Displays when the AI calls Model Context Protocol (MCP) tools (e.g. `query_orders`, `escalate_ticket`, `rag_knowledge_search`).
3. **Escalation & Order Tracking**: Supports human-in-the-loop escalations and order status visualizations.
4. **Zero-Dependency Lightweight Client**: Built with semantic HTML5, CSS3, and modern vanilla ES6+ JavaScript.

---

## 🏃 How to Run Locally

Start the embedded Python multithreaded server:

```bash
# From the frontend-app directory:
python3 server.py
```

The application will be accessible at:
```
http://localhost:3000
```
Make sure the **API Gateway** (`http://localhost:8080`) is running so the frontend can dispatch chat queries and authenticate requests.

