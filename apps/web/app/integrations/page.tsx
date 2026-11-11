"use client";

import { useEffect, useState } from "react";
import { api, type Integration } from "@/lib/api";

const ACCESS_LABEL: Record<Integration["access"], [string, string]> = {
  internal: ["Built in", "ok"],
  official_api: ["Official API", "ok"],
  partner_required: ["Partnership needed", "warn"],
  deep_link: ["You confirm in app", "info"],
};

export default function IntegrationsPage() {
  const [items, setItems] = useState<Integration[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Integration[]>("/integrations")
      .then(setItems)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <h1>Integrations</h1>
      <p className="muted">
        What your agents can actually act through. Where no official API exists, agents prepare the
        action and you confirm it in the provider&apos;s app. They never pretend to complete it.
      </p>
      {error && <p className="error-text">{error}</p>}
      <div className="grid">
        {items?.map((i) => {
          const [label, tone] = ACCESS_LABEL[i.access];
          return (
            <div key={i.key} className="agent">
              <div className="row">
                <strong>{i.name}</strong>
                <span className={`badge ${tone}`}>{label}</span>
              </div>
              <p className="muted small">{i.notes}</p>
              <div className="tools">
                {i.tools.map((t) => (
                  <code key={t}>{t}</code>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}
