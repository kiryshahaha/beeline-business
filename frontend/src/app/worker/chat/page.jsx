// frontend/src/app/worker/chat/page.jsx
"use client";

import React, { useState, useEffect, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/providers/AuthProvider";
import { sendAssistantChat } from "@/lib/worker/api";
import { ASSISTANT_SOURCE_LABELS } from "@/lib/worker/labels";
import styles from "./chat.module.css";

const QUICK_QUESTIONS = [
  "Куда мне дальше?",
  "Во сколько завтра смена?",
  "Почему перенесли заявку?",
  "Что взять с собой?",
];

const INITIAL_MESSAGE = {
  id: "welcome",
  role: "assistant",
  content: "Здравствуйте! Я ваш мобильный ассистент. Могу подсказать ваш следующий адрес, детали по сменам, оборудованию или заявкам. Чем помочь?",
  source_type: "facts",
};

let msgSeq = 0;
function createMsgId(prefix) {
  msgSeq += 1;
  return `${prefix}-${msgSeq}`;
}

function parseTicketId(value) {
  if (!value || !/^\d+$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

function readSavedMessages(storageKey) {
  if (!storageKey || typeof window === "undefined") return [INITIAL_MESSAGE];
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey) || "null");
    if (!Array.isArray(saved)) return [INITIAL_MESSAGE];
    const restored = saved
      .filter(
        (message) =>
          message &&
          (message.role === "user" || message.role === "assistant") &&
          typeof message.content === "string"
      )
      .slice(-99)
      .map((message) => ({
        id: typeof message.id === "string" ? message.id : createMsgId(message.role[0]),
        role: message.role,
        content: message.content.slice(0, 4000),
        source_type: typeof message.source_type === "string" ? message.source_type : undefined,
      }));
    return [INITIAL_MESSAGE, ...restored];
  } catch {
    return [INITIAL_MESSAGE];
  }
}

export default function WorkerChatPage() {
  const { user } = useAuth();
  const searchParams = useSearchParams();
  const initialTicketId = searchParams.get("ticket_id");
  return (
    <WorkerChatConversation
      key={user?.id ?? "guest"}
      userId={user?.id ?? null}
      initialTicketId={initialTicketId}
    />
  );
}

function WorkerChatConversation({ userId, initialTicketId }) {
  const storageKey = userId != null ? `worker_assistant_chat:${userId}` : null;
  const [detachedTicketParam, setDetachedTicketParam] = useState(null);
  const activeTicketId =
    detachedTicketParam === initialTicketId ? null : parseTicketId(initialTicketId);
  const [messages, setMessages] = useState(() => readSavedMessages(storageKey));

  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [errorMessage, setErrorMessage] = useState(null);

  const messagesEndRef = useRef(null);
  const isTypingRef = useRef(false);

  useEffect(() => {
    if (storageKey && typeof window !== "undefined") {
      try {
        sessionStorage.setItem(storageKey, JSON.stringify(messages.slice(-100)));
      } catch {
        // Ignore storage quota and privacy-mode errors.
      }
    }
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping, storageKey]);

  const handleSend = async (textToSend = input) => {
    const text = (textToSend || "").trim();
    if (!text || isTypingRef.current) return;

    setErrorMessage(null);
    setInput("");
    isTypingRef.current = true;
    setIsTyping(true);

    const userMessage = {
      id: createMsgId("u"),
      role: "user",
      content: text,
      ticket_id: activeTicketId,
    };

    const newMessages = [...messages, userMessage];
    setMessages(newMessages);

    // The current message travels in `message`; history contains completed turns only.
    const historyPayload = messages
      .filter((m) => m.id !== "welcome" && (m.role === "user" || m.role === "assistant"))
      .slice(-10)
      .map((m) => ({ role: m.role, content: m.content }));

    try {
      let response;
      let usedTicketContext = Boolean(activeTicketId);
      try {
        response = await sendAssistantChat({
          message: text,
          history: historyPayload,
          ticket_id: activeTicketId,
        });
      } catch (err) {
        if (err.status !== 404 || !activeTicketId) throw err;
        usedTicketContext = false;
        setDetachedTicketParam(initialTicketId);
        response = await sendAssistantChat({
          message: text,
          history: historyPayload,
          ticket_id: null,
        });
      }

      const assistantMessage = {
        id: createMsgId("a"),
        role: "assistant",
        content: `${!usedTicketContext && activeTicketId ? "Контекст заявки недоступен. Ответ дан без него.\n\n" : ""}${response.answer}`,
        source_type: response.source_type,
        sources: response.sources,
        intent: response.intent,
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      setMessages((prev) => prev.filter((message) => message.id !== userMessage.id));
      setInput(text);
      setErrorMessage(err.message || "Помощник временно недоступен");
    } finally {
      isTypingRef.current = false;
      setIsTyping(false);
    }
  };

  const handleClearHistory = () => {
    if (isTypingRef.current) return;
    setMessages([INITIAL_MESSAGE]);
    if (storageKey && typeof window !== "undefined") {
      try {
        sessionStorage.removeItem(storageKey);
      } catch {
        // Ignore storage errors; the visible conversation is still cleared.
      }
    }
  };

  return (
    <div className={styles.container}>
      {/* Top Header */}
      <div className={styles.topHeader}>
        <div className={styles.titleInfo}>
          <h1 className={styles.title}>Чат-помощник</h1>
        </div>
        <button
          type="button"
          className={styles.clearBtn}
          onClick={handleClearHistory}
          disabled={isTyping}
          title="Очистить диалог"
        >
          Очистить
        </button>
      </div>

      {/* Ticket Context Banner if opened for ticket */}
      {activeTicketId && (
        <div className={styles.ticketContextBanner}>
          <span className={styles.contextTag}>Контекст: Заявка №{activeTicketId}</span>
          <button
            type="button"
            className={styles.removeContextBtn}
            onClick={() => setDetachedTicketParam(initialTicketId)}
            disabled={isTyping}
            title="Отвязать контекст заявки"
            aria-label="Отвязать"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      )}

      {/* Messages Scroll Area */}
      <div className={styles.messagesList}>
        {messages.map((m) => {
          const isUser = m.role === "user";
          const sourceLabel = ASSISTANT_SOURCE_LABELS[m.source_type];

          return (
            <div
              key={m.id}
              className={`${styles.messageWrap} ${isUser ? styles.userWrap : styles.assistantWrap}`}
            >
              <div className={`${styles.bubble} ${isUser ? styles.userBubble : styles.assistantBubble}`}>
                <div className={styles.messageText}>{m.content}</div>
                {!isUser && sourceLabel && (
                  <div className={styles.sourceTag}>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ display: "inline-block", verticalAlign: "middle", marginRight: 4 }}>
                      <circle cx="12" cy="12" r="10" />
                      <line x1="12" y1="16" x2="12" y2="12" />
                      <line x1="12" y1="8" x2="12.01" y2="8" />
                    </svg>
                    <span>{sourceLabel}</span>
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {isTyping && (
          <div className={`${styles.messageWrap} ${styles.assistantWrap}`}>
            <div className={`${styles.bubble} ${styles.assistantBubble} ${styles.typingBubble}`}>
              <div className={styles.typingDots}>
                <span />
                <span />
                <span />
              </div>
              <span className={styles.typingText}>Помощник печатает...</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Error banner if occurred */}
      {errorMessage && (
        <div className={styles.errorBanner}>
          <span>{errorMessage}</span>
          <button
            type="button"
            className={styles.closeErrorBtn}
            onClick={() => setErrorMessage(null)}
            aria-label="Закрыть"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      )}

      {/* Quick Suggestion Chips */}
      <div className={styles.chipsScroll}>
        {QUICK_QUESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            className={styles.chip}
            onClick={() => handleSend(q)}
            disabled={isTyping}
          >
            {q}
          </button>
        ))}
      </div>

      {/* Input Form */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleSend();
        }}
        className={styles.inputArea}
      >
        <input
          className={styles.inputField}
          placeholder="Спросите ассистента..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={isTyping}
          maxLength={2000}
        />
        <button
          type="submit"
          className={styles.sendBtn}
          disabled={isTyping || !input.trim()}
          aria-label="Отправить"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </form>
    </div>
  );
}
