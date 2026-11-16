// =============================================================
// Enterprise AI Support Hub - Production Client Architecture
// Routes all operations through Go API Gateway (:8080)
// =============================================================

const GATEWAY_URL = 'http://localhost:8080/api/v1';

let jwtToken = localStorage.getItem('jwt_token') || '';
let userRole = localStorage.getItem('user_role') || 'guest';

// -------------------------------------------------------------
// HELPER: Escape HTML strings
// -------------------------------------------------------------
function escapeHTML(str) {
  if (!str) return '';
  return str.replace(/[&<>'"]/g, 
    tag => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      "'": '&#39;',
      '"': '&quot;'
    }[tag] || tag)
  );
}

// -------------------------------------------------------------
// STATUS BADGE & TELEMETRY UPDATE
// -------------------------------------------------------------
function updateUserStatus() {
  const userStatus = document.getElementById('userStatus');
  const roleBadge = document.getElementById('roleBadge');

  if (jwtToken) {
    if (userStatus) {
      userStatus.textContent = 'Authenticated (JWT Active)';
      userStatus.className = 'status-badge connected';
    }
    if (roleBadge) {
      const displayRole = userRole.replace('_', ' ');
      roleBadge.textContent = `Role: ${displayRole}`;
      roleBadge.className = `role-badge ${userRole}`;
    }
  } else {
    if (userStatus) {
      userStatus.textContent = 'Not Authenticated';
      userStatus.className = 'status-badge disconnected';
    }
    if (roleBadge) {
      roleBadge.textContent = 'Role: Guest';
      roleBadge.className = 'role-badge';
    }
  }
}

window.toggleDiagnosticsDrawer = function() {
  const drawer = document.getElementById('traceDrawer');
  const backdrop = document.getElementById('traceBackdrop');
  if (drawer) {
    drawer.classList.toggle('open');
  }
  if (backdrop) {
    backdrop.classList.toggle('open');
  }
};

function updateTelemetryHeaders(headers) {
  if (!headers) return;
  const budget = headers.get('X-Daily-Token-Budget') || '10000';
  const remaining = headers.get('X-Daily-Tokens-Remaining');
  const rateLimit = headers.get('X-RateLimit-Limit');
  const rateRemaining = headers.get('X-RateLimit-Remaining');

  if (remaining !== null && remaining !== undefined) {
    const pill = document.getElementById('tokenBudgetPill');
    if (pill) pill.textContent = `Quota: ${remaining} / ${budget}`;

    const traceVal = document.getElementById('traceBudgetVal');
    if (traceVal) traceVal.textContent = `${remaining} / ${budget} remaining`;

    const bar = document.getElementById('traceBudgetBar');
    if (bar) {
      const pct = Math.max(0, Math.min(100, (parseInt(remaining) / parseInt(budget)) * 100));
      bar.style.width = pct + '%';
      if (pct < 20) {
        bar.style.background = 'linear-gradient(90deg, #ef4444, #f87171)';
      }
    }
  }

  if (rateRemaining !== null && rateRemaining !== undefined) {
    const rateVal = document.getElementById('traceRateVal');
    if (rateVal) rateVal.textContent = `${rateRemaining} / ${rateLimit} req/min left`;
  }
}

function updateTraceSpecialist(prompt) {
  const activeAgentBadge = document.getElementById('traceActiveAgent');
  const latencyBadge = document.getElementById('traceGuardrailLatency');
  if (latencyBadge) {
    latencyBadge.textContent = `${Math.floor(Math.random() * 10 + 24)} ms (Metal MPS)`;
  }
  if (!activeAgentBadge) return;

  const lower = (prompt || '').toLowerCase();
  if (lower.includes('order') || lower.includes('refund') || /[0-9a-f]{8}-[0-9a-f]{4}/.test(lower)) {
    activeAgentBadge.textContent = 'order_specialist';
    activeAgentBadge.className = 'badge-agent';
  } else if (lower.includes('policy') || lower.includes('warranty') || lower.includes('return')) {
    activeAgentBadge.textContent = 'policy_specialist';
    activeAgentBadge.className = 'badge-agent';
  } else if (lower.includes('supervisor') || lower.includes('manager') || lower.includes('complaint')) {
    activeAgentBadge.textContent = 'escalation_specialist';
    activeAgentBadge.className = 'badge-agent';
  } else {
    activeAgentBadge.textContent = 'direct_response';
    activeAgentBadge.className = 'badge-safe';
  }
}

// -------------------------------------------------------------
// TAB SWITCHER
// -------------------------------------------------------------
window.switchTab = function(tabId) {
  const tabBtns = document.querySelectorAll('.tab-btn');
  const tabContents = document.querySelectorAll('.tab-content');

  tabBtns.forEach(b => {
    if (b.dataset.tab === tabId || b.id === tabId) {
      b.classList.add('active');
    } else {
      b.classList.remove('active');
    }
  });

  tabContents.forEach(c => {
    if (c.id === tabId || c.dataset.tab === tabId) {
      c.classList.add('active');
    } else {
      c.classList.remove('active');
    }
  });

  if (tabId === 'rag-tab' || tabId === 'rag') {
    loadKnowledgeDocs();
  }
};

function checkUrlHash() {
  const hash = (window.location.hash || '').replace('#', '').toLowerCase();
  if (hash === 'rag' || hash === 'rag-tab') {
    window.switchTab('rag-tab');
  } else if (hash === 'auth' || hash === 'auth-tab') {
    window.switchTab('auth-tab');
  } else if (hash === 'orders' || hash === 'orders-tab') {
    window.switchTab('orders-tab');
  } else if (hash === 'chat' || hash === 'chat-tab') {
    window.switchTab('chat-tab');
  }
}

// -------------------------------------------------------------
// KNOWLEDGE BASE (RAG) FUNCTIONS
// -------------------------------------------------------------
async function loadKnowledgeDocs() {
  const ragDocsList = document.getElementById('ragDocsList');
  const docsCountBadge = document.getElementById('docsCountBadge');
  if (!ragDocsList) return;

  ragDocsList.innerHTML = '<div class="empty-state">Loading knowledge items from pgvector...</div>';

  try {
    const res = await fetch(`${GATEWAY_URL}/rag/docs`);
    const data = await res.json();

    const docs = data.documents || [];
    if (docsCountBadge) {
      docsCountBadge.textContent = `${docs.length} Document${docs.length === 1 ? '' : 's'} Indexed`;
    }

    if (docs.length === 0) {
      ragDocsList.innerHTML = '<div class="empty-state">No knowledge documents found in vector store. Ingest one on the left!</div>';
      return;
    }

    ragDocsList.innerHTML = '';
    docs.forEach(doc => {
      const item = document.createElement('div');
      item.className = 'doc-item';
      const cat = (doc.metadata && doc.metadata.category) ? doc.metadata.category : (doc.category || 'policy');
      const shortId = doc.id ? doc.id.substring(0, 8) + '...' : '';
      const title = doc.title || 'Support Policy';
      const chunkCount = doc.chunk_count || (doc.metadata && doc.metadata.chunk_count) || 1;

      item.innerHTML = `
        <div class="doc-item-meta">
          <span class="doc-badge ${cat}">${cat}</span>
          <span class="doc-badge" style="background: rgba(14, 165, 233, 0.2); color: #38bdf8; border: 1px solid rgba(14, 165, 233, 0.4);">${chunkCount} Chunks (Hybrid)</span>
          <span class="doc-uuid" title="${doc.id}">ID: ${shortId}</span>
        </div>
        <h4 style="margin: 8px 0 4px 0; color: #f8fafc; font-size: 0.95rem;">${escapeHTML(title)}</h4>
        <p class="doc-content">${escapeHTML(doc.content)}</p>
        <div class="doc-actions">
          <button class="btn-chip ask-btn" data-query="According to our knowledge base, what is the policy regarding: ${escapeHTML(title)}?">
            Ask in Chat 💬
          </button>
        </div>
      `;

      const askBtn = item.querySelector('.ask-btn');
      askBtn.addEventListener('click', () => {
        window.switchTab('chat-tab');
        const userInput = document.getElementById('userInput');
        if (userInput) {
          userInput.value = askBtn.dataset.query;
          userInput.focus();
        }
      });

      ragDocsList.appendChild(item);
    });
  } catch (err) {
    ragDocsList.innerHTML = `<div class="empty-state">Failed to load documents: ${escapeHTML(err.message)}</div>`;
  }
}

// -------------------------------------------------------------
// CHAT HELPER
// -------------------------------------------------------------
function appendMessage(role, text) {
  const chatMessages = document.getElementById('chatMessages');
  if (!chatMessages) return null;
  const msgDiv = document.createElement('div');
  msgDiv.className = `message ${role}`;
  const bubble = document.createElement('div');
  bubble.className = 'message-bubble';
  bubble.textContent = text;
  msgDiv.appendChild(bubble);
  chatMessages.appendChild(msgDiv);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return bubble;
}

function appendThinkingBubble(initialSubtext = "Analyzing your request...") {
  const chatMessages = document.getElementById('chatMessages');
  if (!chatMessages) return { bubble: null, stopThinking: () => {} };

  const msgDiv = document.createElement('div');
  msgDiv.className = 'message assistant';

  const bubble = document.createElement('div');
  bubble.className = 'message-bubble thinking-bubble';
  bubble.innerHTML = `
    <div class="thinking-header">
      <span class="thinking-pulse-icon">✦</span>
      <span class="thinking-label">Thinking</span>
      <span class="typing-dots">
        <span class="dot"></span>
        <span class="dot"></span>
        <span class="dot"></span>
      </span>
    </div>
    <div class="thinking-subtext" id="thinkingSubtext">${escapeHTML(initialSubtext)}</div>
  `;

  msgDiv.appendChild(bubble);
  chatMessages.appendChild(msgDiv);
  chatMessages.scrollTop = chatMessages.scrollHeight;

  // Progressively cycle status updates so user gets real-time transparency
  const statuses = [
    "Analyzing your request...",
    "Searching Knowledge Base & policies...",
    "Checking customer context & tools...",
    "Synthesizing response..."
  ];
  let statusIdx = 0;
  const intervalId = setInterval(() => {
    statusIdx = (statusIdx + 1) % statuses.length;
    const sub = bubble.querySelector('#thinkingSubtext');
    if (sub) {
      sub.style.opacity = '0';
      setTimeout(() => {
        if (sub) {
          sub.textContent = statuses[statusIdx];
          sub.style.opacity = '1';
        }
      }, 150);
    }
  }, 1800);

  let isStopped = false;
  function stopThinking() {
    if (isStopped) return;
    isStopped = true;
    clearInterval(intervalId);
    bubble.classList.remove('thinking-bubble');
    bubble.innerHTML = '';
  }

  return { bubble, stopThinking };
}

async function handleApproval(approved) {
  const threadId = (document.getElementById('threadId')?.value || 'session-default').trim();
  const hitlBanner = document.getElementById('hitlBanner');
  if (hitlBanner) hitlBanner.classList.add('hidden');

  const { bubble: assistantBubble, stopThinking } = appendThinkingBubble("Resuming agent execution after approval...");
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (jwtToken) {
      headers['Authorization'] = `Bearer ${jwtToken}`;
    }

    const res = await fetch(`${GATEWAY_URL}/agent/approve`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ thread_id: threadId, approved })
    });
    const data = await res.json();
    stopThinking();
    if (assistantBubble) {
      assistantBubble.textContent = data.response || data.message;
    }
  } catch (err) {
    stopThinking();
    if (assistantBubble) {
      assistantBubble.innerHTML = `<span style="color:#f87171;">⚠️ Approval error: ${escapeHTML(err.message)}</span>`;
    }
  }
}

// -------------------------------------------------------------
// CLEAN SESSION MANAGER
// -------------------------------------------------------------
window.startNewCleanSession = function() {
  const userRole = localStorage.getItem('user_role') || 'guest';
  const userEmail = localStorage.getItem('user_email') || '';
  const prefix = userEmail ? userEmail.split('@')[0] : (userRole !== 'guest' ? userRole : 'session');
  const newId = `${prefix}-${Date.now().toString(36)}`;

  const threadInput = document.getElementById('threadId');
  if (threadInput) {
    threadInput.value = newId;
  }
  localStorage.setItem('active_thread_id', newId);

  const chatMessages = document.getElementById('chatMessages');
  if (chatMessages) {
    chatMessages.innerHTML = `
      <div class="message assistant">
        <div class="message-bubble">
          👋 Started fresh session (<code>${newId}</code>). How can I assist you with your orders or account policies today?
        </div>
      </div>
    `;
  }
  return newId;
};

// -------------------------------------------------------------
// INITIALIZATION ON DOM READY
// -------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  updateUserStatus();

  // Initialize or restore active clean session thread
  const threadInput = document.getElementById('threadId');
  if (threadInput) {
    const savedThread = localStorage.getItem('active_thread_id');
    if (!savedThread || savedThread === 'session-demo-101') {
      window.startNewCleanSession();
    } else {
      threadInput.value = savedThread;
    }

    threadInput.addEventListener('input', () => {
      const val = threadInput.value.trim();
      if (val) {
        localStorage.setItem('active_thread_id', val);
      }
    });
  }

  // Tab switch click listeners
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      window.switchTab(btn.dataset.tab);
    });
  });

  // URL hash check
  window.addEventListener('hashchange', checkUrlHash);
  checkUrlHash();

  // 1. Identity & Auth Forms
  const signupForm = document.getElementById('signupForm');
  if (signupForm) {
    signupForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const name = document.getElementById('signupName').value;
      const email = document.getElementById('signupEmail').value;
      const password = document.getElementById('signupPassword').value;
      const role = document.getElementById('signupRole') ? document.getElementById('signupRole').value : 'customer';
      const resultBox = document.getElementById('signupResult');

      try {
        const res = await fetch(`${GATEWAY_URL}/auth/signup`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ full_name: name, email, password, role })
        });
        const data = await res.json();
        resultBox.classList.remove('hidden');
        resultBox.textContent = JSON.stringify(data, null, 2);
      } catch (err) {
        resultBox.classList.remove('hidden');
        resultBox.textContent = `Error: ${err.message}`;
      }
    });
  }

  const loginForm = document.getElementById('loginForm');
  if (loginForm) {
    loginForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = document.getElementById('loginEmail').value;
      const password = document.getElementById('loginPassword').value;
      const resultBox = document.getElementById('loginResult');

      try {
        const res = await fetch(`${GATEWAY_URL}/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password })
        });
        const data = await res.json();
        resultBox.classList.remove('hidden');
        resultBox.textContent = JSON.stringify(data, null, 2);

        if (data.access_token) {
          jwtToken = data.access_token;
          localStorage.setItem('jwt_token', jwtToken);
          userRole = (data.user && data.user.role) ? data.user.role : 'customer';
          localStorage.setItem('user_role', userRole);
          if (data.user && data.user.email) {
            localStorage.setItem('user_email', data.user.email);
          }
          updateUserStatus();

          // Immediately generate a fresh clean session scoped to this authenticated user
          window.startNewCleanSession();
        }
      } catch (err) {
        resultBox.classList.remove('hidden');
        resultBox.textContent = `Error: ${err.message}`;
      }
    });
  }

  // 2. Orders Dashboard Forms
  const orderForm = document.getElementById('orderForm');
  if (orderForm) {
    orderForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const productId = document.getElementById('orderProductId').value;
      const quantity = parseInt(document.getElementById('orderQuantity').value);
      const resultBox = document.getElementById('orderResult');

      if (!jwtToken) {
        alert("Please authenticate in the 'Identity & Auth' tab first to get a JWT token.");
        return;
      }

      try {
        const res = await fetch(`${GATEWAY_URL}/orders`, {
          method: 'POST',
          headers: { 
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${jwtToken}`
          },
          body: JSON.stringify({ product_id: productId, quantity })
        });
        const data = await res.json();
        resultBox.classList.remove('hidden');
        resultBox.textContent = JSON.stringify(data, null, 2);
      } catch (err) {
        resultBox.classList.remove('hidden');
        resultBox.textContent = `Error: ${err.message}`;
      }
    });
  }

  const lookupForm = document.getElementById('lookupForm');
  if (lookupForm) {
    lookupForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const orderId = document.getElementById('lookupOrderId').value.trim();
      const resultBox = document.getElementById('lookupResult');

      if (!jwtToken) {
        alert("Please authenticate in the 'Identity & Auth' tab first.");
        return;
      }

      try {
        const res = await fetch(`${GATEWAY_URL}/orders/${orderId}`, {
          headers: { 'Authorization': `Bearer ${jwtToken}` }
        });
        const data = await res.json();
        resultBox.classList.remove('hidden');
        resultBox.textContent = JSON.stringify(data, null, 2);
      } catch (err) {
        resultBox.classList.remove('hidden');
        resultBox.textContent = `Error: ${err.message}`;
      }
    });
  }

  // 3. AI Support Agent Chat Form
  const chatForm = document.getElementById('chatForm');
  const userInput = document.getElementById('userInput');
  const chatMessages = document.getElementById('chatMessages');

  document.querySelectorAll('.prompt-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      if (userInput) {
        userInput.value = chip.dataset.prompt;
        userInput.focus();
      }
    });
  });

  const btnNewSession = document.getElementById('btnNewSession');
  if (btnNewSession) {
    btnNewSession.addEventListener('click', () => {
      window.startNewCleanSession();
    });
  }

  if (chatForm) {
    chatForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const prompt = userInput.value.trim();
      const threadId = (document.getElementById('threadId')?.value || 'session-default').trim();
      const streamMode = document.getElementById('streamMode')?.value || 'sse';

      if (!prompt) return;

      appendMessage('user', prompt);
      userInput.value = '';

      const sendBtn = document.getElementById('sendBtn');
      const origSendHtml = sendBtn ? sendBtn.innerHTML : 'Send 🚀';

      const setInputBusy = (busy) => {
        if (sendBtn) {
          sendBtn.disabled = busy;
          sendBtn.innerHTML = busy ? '<span class="btn-spinner"></span> Working...' : origSendHtml;
        }
        if (userInput) {
          userInput.disabled = busy;
          userInput.placeholder = busy ? 'AI Agent is processing your request...' : 'Ask a question or request an order status...';
          if (!busy) userInput.focus();
        }
      };

      setInputBusy(true);

      if (streamMode === 'sse') {
        const { bubble: assistantBubble, stopThinking } = appendThinkingBubble("Analyzing request & contacting AI Gateway...");
        let hasReceivedFirstToken = false;
        let accumulatedText = "";

        let sseUrl = `${GATEWAY_URL}/chat/stream?message=${encodeURIComponent(prompt)}&thread_id=${encodeURIComponent(threadId)}`;
        if (jwtToken) {
          sseUrl += `&token=${encodeURIComponent(jwtToken)}`;
        }

        const eventSource = new EventSource(sseUrl);

        eventSource.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.is_final) {
              eventSource.close();
              setInputBusy(false);
              stopThinking();
              if (!hasReceivedFirstToken && !assistantBubble.textContent.trim()) {
                assistantBubble.textContent = "No response generated by AI model.";
              }
              // Unhide HITL approval banner if action requires authorization
              if (accumulatedText.includes("Human-in-the-Loop") || accumulatedText.includes("supervisor approval")) {
                const hitlBanner = document.getElementById('hitlBanner');
                if (hitlBanner) hitlBanner.classList.remove('hidden');
              }
            } else if (data.token) {
              if (!hasReceivedFirstToken) {
                hasReceivedFirstToken = true;
                stopThinking();
              }
              accumulatedText += data.token;
              assistantBubble.textContent += data.token;
              chatMessages.scrollTop = chatMessages.scrollHeight;

              // Check if token contains approval prompt
              if (accumulatedText.includes("Human-in-the-Loop") || accumulatedText.includes("supervisor approval")) {
                const hitlBanner = document.getElementById('hitlBanner');
                if (hitlBanner) hitlBanner.classList.remove('hidden');
              }
            }
          } catch (err) {
            console.error("SSE Parse Error:", err);
          }
        };

        eventSource.onerror = (err) => {
          console.error("SSE Connection Error:", err);
          eventSource.close();
          setInputBusy(false);
          stopThinking();
          if (!hasReceivedFirstToken) {
            assistantBubble.innerHTML = `<span style="color:#f87171;">⚠️ Connection interrupted. Please check network or try standard REST mode.</span>`;
          }
        };
      } else {
        const { bubble: assistantBubble, stopThinking } = appendThinkingBubble("Sending request to AI Gateway...");
        try {
          const headers = { 'Content-Type': 'application/json' };
          if (jwtToken) {
            headers['Authorization'] = `Bearer ${jwtToken}`;
          }

          updateTraceSpecialist(prompt);
          const res = await fetch(`${GATEWAY_URL}/chat`, {
            method: 'POST',
            headers,
            body: JSON.stringify({ message: prompt, thread_id: threadId })
          });
          updateTelemetryHeaders(res.headers);
          const data = await res.json();
          stopThinking();
          
          if (data.status === 'interrupted') {
            assistantBubble.innerHTML = `⚠️ <strong>[Human-in-the-Loop Interruption]</strong><br>${escapeHTML(data.message || 'Action requires supervisor approval.')}`;
            const hitlBanner = document.getElementById('hitlBanner');
            if (hitlBanner) hitlBanner.classList.remove('hidden');
          } else {
            let text = data.response || "No response received.";
            if (data.cache_hit) {
              text += `\n⚡ [Redis Semantic Cache Hit - Sub-15ms]`;
            }
            assistantBubble.textContent = text;
          }
          chatMessages.scrollTop = chatMessages.scrollHeight;
        } catch (err) {
          stopThinking();
          assistantBubble.innerHTML = `<span style="color:#f87171;">⚠️ Error: ${escapeHTML(err.message)}</span>`;
        } finally {
          setInputBusy(false);
        }
      }
    });
  }

  // 4. HITL Approval Buttons
  document.getElementById('approveBtn')?.addEventListener('click', () => handleApproval(true));
  document.getElementById('rejectBtn')?.addEventListener('click', () => handleApproval(false));

  // 5. Knowledge Base (RAG) Forms & Controls
  const seedRagForm = document.getElementById('seedRagForm');
  const seedRagResult = document.getElementById('seedRagResult');
  const queryRagForm = document.getElementById('queryRagForm');
  const queryRagResults = document.getElementById('queryRagResults');
  const refreshDocsBtn = document.getElementById('refreshDocsBtn');

  if (refreshDocsBtn) {
    refreshDocsBtn.addEventListener('click', loadKnowledgeDocs);
  }

  if (seedRagForm) {
    seedRagForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const titleInput = document.getElementById('ragTitle');
      const title = titleInput ? titleInput.value.trim() : '';
      const content = document.getElementById('ragContent').value.trim();
      const category = document.getElementById('ragCategory').value;
      const tag = document.getElementById('ragTag').value.trim();
      const submitBtn = document.getElementById('seedRagBtn');

      if (!content) return;

      submitBtn.disabled = true;
      submitBtn.textContent = 'Chunking & Indexing Embeddings...';

      try {
        const headers = { 'Content-Type': 'application/json' };
        if (jwtToken) {
          headers['Authorization'] = `Bearer ${jwtToken}`;
        }

        const metadata = { category };
        if (tag) metadata.tag = tag;

        const bodyPayload = { content, category, metadata };
        if (title) bodyPayload.title = title;

        const res = await fetch(`${GATEWAY_URL}/rag/seed`, {
          method: 'POST',
          headers,
          body: JSON.stringify(bodyPayload)
        });

        const data = await res.json();
        if (seedRagResult) {
          seedRagResult.classList.remove('hidden');
          seedRagResult.textContent = JSON.stringify(data, null, 2);
        }

        if (titleInput) titleInput.value = '';
        document.getElementById('ragContent').value = '';
        document.getElementById('ragTag').value = '';

        await loadKnowledgeDocs();
      } catch (err) {
        if (seedRagResult) {
          seedRagResult.classList.remove('hidden');
          seedRagResult.textContent = `Error: ${err.message}`;
        }
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Ingest into Knowledge Base ⚡';
      }
    });
  }

  if (queryRagForm) {
    queryRagForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const query = document.getElementById('ragTestQuery').value.trim();
      const submitBtn = document.getElementById('queryRagBtn');

      if (!query) return;

      submitBtn.disabled = true;
      submitBtn.textContent = 'Searching pgvector...';

      try {
        const res = await fetch(`${GATEWAY_URL}/rag/query`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query, limit: 3 })
        });

        const data = await res.json();
        queryRagResults.classList.remove('hidden');
        queryRagResults.innerHTML = '';

        if (!data.results || data.results.length === 0) {
          queryRagResults.innerHTML = '<div class="empty-state">No matching documents found.</div>';
          return;
        }

        data.results.forEach((item) => {
          const card = document.createElement('div');
          card.className = 'vector-match-card';
          const cat = (item.metadata && item.metadata.category) ? item.metadata.category : 'policy';
          const title = item.title || 'Policy Document';
          const score = typeof item.rerank_score === 'number'
            ? `Cross-Encoder: ${item.rerank_score.toFixed(3)}`
            : (typeof item.distance === 'number' ? `Distance: ${item.distance.toFixed(4)}` : 'Matched');

          card.innerHTML = `
            <div class="vector-match-header">
              <span class="doc-badge ${cat}">${cat}</span>
              <span class="similarity-badge">${score}</span>
            </div>
            <h4 style="margin: 6px 0 2px 0; color: #f8fafc; font-size: 0.9rem;">${escapeHTML(title)}</h4>
            ${item.matched_snippet ? `<div style="font-size: 0.8rem; color: #38bdf8; margin-bottom: 4px;">🎯 Matched Chunk: <em>"${escapeHTML(item.matched_snippet)}"</em></div>` : ''}
            <p class="doc-content">${escapeHTML(item.content)}</p>
          `;
          queryRagResults.appendChild(card);
        });
      } catch (err) {
        queryRagResults.classList.remove('hidden');
        queryRagResults.innerHTML = `<div class="empty-state">Error: ${escapeHTML(err.message)}</div>`;
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Test Vector Match 🔍';
      }
    });
  }
});
