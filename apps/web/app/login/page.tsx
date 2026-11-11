"use client";

import { useState, type FormEvent } from "react";
import { supabase } from "@/lib/supabase";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const { error } = await supabase().auth.signInWithOtp({
      email,
      options: { emailRedirectTo: window.location.origin, shouldCreateUser: false },
    });
    setBusy(false);
    if (error) setError(error.message);
    else setSent(true);
  };

  return (
    <main className="center">
      <form className="card login" onSubmit={submit}>
        <h1>Workforce OS</h1>
        <p className="muted">Sign in with a one-time link sent to your email.</p>
        {sent ? (
          <p>Check {email} for your sign-in link.</p>
        ) : (
          <>
            <input
              type="email"
              required
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <button type="submit" disabled={busy}>
              {busy ? "Sending…" : "Send sign-in link"}
            </button>
          </>
        )}
        {error && <p className="error-text">{error}</p>}
      </form>
    </main>
  );
}
