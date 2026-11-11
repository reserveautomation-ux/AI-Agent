"use client";

import type { Session } from "@supabase/supabase-js";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { supabase } from "@/lib/supabase";

const SessionContext = createContext<Session | null>(null);

export function useSession() {
  return useContext(SessionContext);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    let client;
    try {
      client = supabase();
    } catch (e) {
      setConfigError((e as Error).message);
      setReady(true);
      return;
    }
    client.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setReady(true);
    });
    const { data } = client.auth.onAuthStateChange((_event, s) => setSession(s));
    return () => data.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (!ready || configError) return;
    if (!session && pathname !== "/login") router.replace("/login");
    if (session && pathname === "/login") router.replace("/");
  }, [ready, session, pathname, router, configError]);

  if (configError) {
    return (
      <main className="center">
        <div className="card">
          <h2>Configuration needed</h2>
          <p className="muted">{configError}</p>
        </div>
      </main>
    );
  }
  if (!ready || (!session && pathname !== "/login")) {
    return <main className="center muted">Loading…</main>;
  }
  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>;
}
