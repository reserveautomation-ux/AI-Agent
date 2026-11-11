"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** Old address: Integrations is now Connections (keeps ?connected=… from older sign-in links). */
export default function IntegrationsRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace(`/connections${window.location.search}`);
  }, [router]);
  return <p className="muted">Opening Connections…</p>;
}
