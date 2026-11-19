/**
 * chat/chat.js
 * Asisten Tata Ruang chat dock interface, message history rendering,
 * markdown parsing, guardrail status badges, and validated legal citation lists.
 */

import { state } from "../state.js";
import { postChatMessage } from "../api.js";
import { escapeHtml } from "../utils/dom.js";
import { executeMapActions } from "../map/actions.js";

export function renderMarkdown(rawText) {
  if (!rawText) return "";
  if (rawText.startsWith("<em>") || rawText.startsWith("Halo! Saya adalah <strong>")) {
    return rawText;
  }

  const escaped = escapeHtml(rawText);
  const lines = escaped.split("\n");
  let html = "";
  let inList = false;

  for (let i = 0; i < lines.length; i++) {
    let line = lines[i];

    if (/^###\s+(.*)/.test(line)) {
      if (inList) { html += "</ul>"; inList = false; }
      html += line.replace(/^###\s+(.*)/, '<h4 style="margin: 8px 0 4px; font-size: 13px; font-weight: 700; color: #fff;">$1</h4>');
      continue;
    }
    if (/^##\s+(.*)/.test(line)) {
      if (inList) { html += "</ul>"; inList = false; }
      html += line.replace(/^##\s+(.*)/, '<h3 style="margin: 10px 0 6px; font-size: 14px; font-weight: 800; color: #fff;">$1</h3>');
      continue;
    }
    if (/^#\s+(.*)/.test(line)) {
      if (inList) { html += "</ul>"; inList = false; }
      html += line.replace(/^#\s+(.*)/, '<h2 style="margin: 12px 0 8px; font-size: 15px; font-weight: 800; color: #fff;">$1</h2>');
      continue;
    }

    if (/^[\*\-]\s+(.*)/.test(line)) {
      if (!inList) { html += '<ul style="margin: 4px 0 6px 18px; padding: 0;">'; inList = true; }
      const itemContent = line.replace(/^[\*\-]\s+(.*)/, '$1')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, '<code style="background: rgba(255,255,255,0.1); padding: 1px 4px; border-radius: 4px;">$1</code>');
      html += `<li style="margin-bottom: 3px;">${itemContent}</li>`;
      continue;
    }

    if (inList) {
      html += "</ul>";
      inList = false;
    }

    if (!line.trim()) {
      html += '<div style="height: 6px;"></div>';
      continue;
    }

    let formatted = line
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`([^`]+)`/g, '<code style="background: rgba(255,255,255,0.1); padding: 1px 4px; border-radius: 4px;">$1</code>');
    html += `<p style="margin: 3px 0;">${formatted}</p>`;
  }

  if (inList) {
    html += "</ul>";
  }

  return html;
}

export function appendChatMessage(role, content) {
  const history = document.getElementById("chat-history");
  if (!history) return "";
  const row = document.createElement("div");
  const msgId = `msg-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
  row.className = `chat-message-row ${role}`;
  row.innerHTML = `
    <div class="chat-bubble" id="${msgId}">
      ${role === 'assistant' ? renderMarkdown(content) : escapeHtml(content)}
    </div>
  `;
  history.appendChild(row);
  history.scrollTop = history.scrollHeight;
  state.chatMessages.push({ role, content });
  return msgId;
}

export async function handleSendMessage() {
  const input = document.getElementById("chat-msg-input");
  if (!input) return;
  const text = input.value.trim();
  if (!text) return;

  appendChatMessage("user", text);
  input.value = "";

  const thinkingId = appendChatMessage("assistant", "<em>Sedang memproses pemanggilan alat spasial PostGIS & inferensi AI...</em>");

  try {
    const payload = {
      messages: state.chatMessages.map(m => ({ role: m.role, content: m.content })),
      district_context: state.selectedDistrict ? state.selectedDistrict.kemendagri_code : null
    };

    const data = await postChatMessage(payload);

    const bubbleEl = document.getElementById(thinkingId);
    if (bubbleEl) {
      let html = renderMarkdown(data.reply || "");

      if (data.guardrail) {
        const badgeClass = data.guardrail === "passed" ? "passed" : data.guardrail === "retried" ? "retried" : "numeric_fallback";
        const badgeLabel = data.guardrail === "passed" ? "Guardrail: Passed" : data.guardrail === "retried" ? "Guardrail: Retried" : "Guardrail: Fallback";
        html = `
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
            <span style="font-size: 11px; color: var(--text-dim);">Asisten Tata Ruang</span>
            <span class="guardrail-badge ${badgeClass}">${badgeLabel}</span>
          </div>
        ` + html;
      }

      if (data.citations && Array.isArray(data.citations) && data.citations.length > 0) {
        let citHtml = `
          <div class="chat-citations-container">
            <div class="chat-citations-title">📜 Rujukan Hukum Terverifikasi (${data.citations.length}):</div>
            <ul class="chat-citations-list">
        `;
        data.citations.forEach(c => {
          const title = c.regulation_code ? `${c.regulation_code} - ${c.title || ''}` : (c.title || String(c));
          const art = c.article_reference ? ` <em>(${escapeHtml(c.article_reference)})</em>` : '';
          citHtml += `<li><strong>${escapeHtml(title)}</strong>${art}</li>`;
        });
        citHtml += `</ul></div>`;
        html += citHtml;
      }

      bubbleEl.innerHTML = html;
    }

    if (data.map_actions && data.map_actions.length > 0) {
      await executeMapActions(data.map_actions);
    }
  } catch (err) {
    const bubbleEl = document.getElementById(thinkingId);
    if (bubbleEl) {
      bubbleEl.textContent = `Maaf, terjadi kendala koneksi ke server AI: ${err.message}`;
    }
  }
}

export function initChatbot() {
  const dock = document.getElementById("chatbot-dock");
  const toggleBtn = document.getElementById("btn-toggle-chat");
  const input = document.getElementById("chat-msg-input");
  const sendBtn = document.getElementById("btn-send-chat");

  if (toggleBtn && dock) {
    toggleBtn.addEventListener("click", () => {
      dock.classList.toggle("collapsed");
      toggleBtn.textContent = dock.classList.contains("collapsed") ? "▲ Expand" : "▼ Minimize";
    });
  }

  if (sendBtn) sendBtn.addEventListener("click", handleSendMessage);
  if (input) {
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") handleSendMessage();
    });
  }

  document.querySelectorAll(".prompt-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      if (input) {
        input.value = chip.textContent;
        handleSendMessage();
      }
    });
  });
}
