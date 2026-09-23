"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/providers/AuthProvider";

export default function LoginPage() {
  const [username, setUsername] = useState("demo_observer");
  const [password, setPassword] = useState("ObserverSecret123!");
  const [error, setError] = useState(null);
  const router = useRouter();
  const { login } = useAuth();

  const handleLogin = async (e) => {
    e.preventDefault();
    setError(null);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_ENDPOINT}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include", // чтобы браузер принял httpOnly cookie из ответа
        body: JSON.stringify({ username, password })
      });
      
      if (!res.ok) {
        throw new Error("Неверный логин или пароль");
      }
      
      const data = await res.json();
      // Сохраняем только access_token — refresh_token сервер поставил в cookie сам
      login(data.access_token);
      router.push("/");
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div style={{ padding: "50px", fontFamily: "sans-serif" }}>
      <h1>Демо Логин</h1>
      <form onSubmit={handleLogin} style={{ display: "flex", flexDirection: "column", gap: "10px", maxWidth: "300px" }}>
        <input 
          value={username} 
          onChange={e => setUsername(e.target.value)} 
          placeholder="Логин" 
          style={{ padding: "10px", borderRadius: "8px", border: "1px solid #ccc", background: "#fff", color: "#000" }}
        />
        <input 
          type="password" 
          value={password} 
          onChange={e => setPassword(e.target.value)} 
          placeholder="Пароль" 
          style={{ padding: "10px", borderRadius: "8px", border: "1px solid #ccc", background: "#fff", color: "#000" }}
        />
        <button type="submit" style={{ padding: "10px", borderRadius: "8px", cursor: "pointer", background: "#000", color: "#fff" }}>
          Войти
        </button>
      </form>
      {error && <p style={{ color: "red" }}>{error}</p>}
    </div>
  );
}
