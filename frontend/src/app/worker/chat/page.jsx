// frontend/src/app/worker/chat/page.jsx
"use client";

import React, { useState, useEffect, useRef } from "react";
import { useSearchParams } from "next/navigation";
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

export default function WorkerChatPage() {
  const searchParams = useSearchParams();
  const initialTicketId = searchParams.get("ticket_id");

  const [activeTicketId, setActiveTicketId] = useState(
    initialTicketId ? parseInt(initialTicketId, 10) : null
  );

  const [messages, setMessages] = useState(() => {
    if (typeof window !== "undefined") {
      try {
        const saved = sessionStorage.getItem("worker_assistant_chat");
        if (saved) return JSON.parse(saved);
      } catch {
        // ignore
      }
    }
    return [INITIAL_MESSAGE];
  });

  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [errorMessage, setErrorMessage] = useState(null);

  const messagesEndRef = useRef(null);

  useEffect(() => {
    if (typeof window !== "undefined") {
      try {
        sessionStorage.setItem("worker_assistant_chat", JSON.stringify(messages));
      } catch {
        // ignore
      }
    }
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  const handleSend = async (textToSend = input) => {
    const text = (textToSend || "").trim();
    if (!text || isTyping) return;

    setErrorMessage(null);
    setInput("");

    const userMessage = {
      id: createMsgId("u"),
      role: "user",
      content: text,
      ticket_id: activeTicketId,
    };

    const newMessages = [...messages, userMessage];
    setMessages(newMessages);
    setIsTyping(true);

    // Prepare history: last <= 10 messages of user/assistant
    const historyPayload = newMessages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .slice(-10)
      .map((m) => ({ role: m.role, content: m.content }));

    try {
      const response = await sendAssistantChat({
        message: text,
        history: historyPayload,
        ticket_id: activeTicketId,
      });

      const assistantMessage = {
        id: createMsgId("a"),
        role: "assistant",
        content: response.answer || "Ответ получен",
        source_type: response.source_type,
        sources: response.sources,
        intent: response.intent,
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      if (err.message === "Заявка снята" && activeTicketId) {
        // Retry without ticket_id as required in specs
        setActiveTicketId(null);
        try {
          const fallbackRes = await sendAssistantChat({
            message: text,
            history: historyPayload,
            ticket_id: null,
          });
          const assistantMessage = {
            id: createMsgId("a"),
            role: "assistant",
            content: fallbackRes.answer,
            source_type: fallbackRes.source_type,
          };
          setMessages((prev) => [...prev, assistantMessage]);
          return;
        } catch (retryErr) {
          setErrorMessage(retryErr.message);
        }
      } else {
        setErrorMessage(err.message || "Помощник временно недоступен");
      }
    } finally {
      setIsTyping(false);
    }
  };

  const handleClearHistory = () => {
    setMessages([INITIAL_MESSAGE]);
    if (typeof window !== "undefined") {
      sessionStorage.removeItem("worker_assistant_chat");
    }
  };

  return (
    <div className={styles.container}>
      {/* Top Header */}
      <div className={styles.topHeader}>
        <div className={styles.titleInfo}>
          <h1 className={styles.title}>Чат-помощник</h1>
          <span className={styles.onlineBadge}>● Онлайн</span>
        </div>
        <button
          type="button"
          className={styles.clearBtn}
          onClick={handleClearHistory}
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
            onClick={() => setActiveTicketId(null)}
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
