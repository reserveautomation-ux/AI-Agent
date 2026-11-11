"use client";

import { Connections } from "@/components/Connections";

export default function ConnectionsPage() {
  return (
    <>
      <h1>Connections</h1>
      <p className="muted">
        Connect a service only when you need it. If a task needs one you haven&apos;t connected, it
        waits and tells you, then carries on by itself once you connect. Keys and sign-ins are
        stored encrypted and never shown again. Services without an official way in (cabs, food,
        movies) open in their own app for you to confirm.
      </p>
      <Connections />
    </>
  );
}
