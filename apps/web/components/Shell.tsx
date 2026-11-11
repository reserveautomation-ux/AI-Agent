"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api, post, type Me } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { useSession } from "./AuthProvider";

const NAV = [
  { href: "/", label: "Command" },
  { href: "/approvals", label: "Approvals" },
  { href: "/workforce", label: "Workforce" },
  { href: "/memory", label: "Memory" },
  { href: "/connections", label: "Connections" },
  { href: "/audit", label: "Audit" },
];

export function Shell({ children }: { children: ReactNode }) {
  const session = useSession();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingCount, setPendingCount] = useState(0);

  const load = useCallback(() => {
    api<Me>("/me").then(setMe).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (session) load();
  }, [session, load]);

  // Badge on "Approvals": how many actions are waiting for the owner.
  useEffect(() => {
    if (!session) return;
    const count = () =>
      api<unknown[]>("/approvals?limit=99")
        .then((l) => setPendingCount(l.length))
        .catch(() => {});
    count();
    const t = setInterval(count, 15000);
    return () => clearInterval(t);
  }, [session, pathname]);

  if (!session || pathname === "/login") return <>{children}</>;

  const toggleKillSwitch = async () => {
    if (!me) return;
    const enabling = !me.workspace.kill_switch;
    if (enabling && !confirm("Stop all agent activity and block new tasks?")) return;
    try {
      const ws = await post<Me["workspace"]>("/workspace/kill-switch", { enabled: enabling });
      setMe({ ...me, workspace: ws });
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <>
      <header className="topbar">
        <Link href="/" className="brand">
          Workforce OS
        </Link>
        <nav>
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} className={pathname === n.href ? "active" : ""}>
              {n.label}
              {n.href === "/approvals" && pendingCount > 0 && (
                <span className="count" aria-label={`${pendingCount} waiting`}>
                  {pendingCount}
                </span>
              )}
            </Link>
          ))}
        </nav>
        <div className="topbar-actions">
          {me?.workspace.role === "owner" && (
            <button
              className={me.workspace.kill_switch ? "danger" : "ghost"}
              onClick={toggleKillSwitch}
              title="Emergency stop"
            >
              {me.workspace.kill_switch ? "Stopped — resume" : "Stop all"}
            </button>
          )}
          <button className="ghost" onClick={() => supabase().auth.signOut()}>
            Sign out
          </button>
        </div>
      </header>
      {me?.workspace.kill_switch && (
        <div className="banner">Kill switch is on. Agents are stopped and new tasks are blocked.</div>
      )}
      {error && <div className="banner error">{error}</div>}
      <main className="container">{children}</main>
    </>
  );
}
