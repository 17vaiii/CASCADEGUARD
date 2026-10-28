import { ExternalLink } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import type { Provenance_ } from "../../lib/types";

export function SourcesView() {
  const [p, setP] = useState<Provenance_ | null>(null);
  useEffect(() => { api.provenance().then(setP).catch(() => undefined); }, []);
  if (!p) return <div className="p-6 text-ink-3">Loading…</div>;
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[900px] space-y-8 p-6 text-[14px] leading-relaxed">
        <header>
          <h1 className="font-cond text-[24px] font-semibold">What is real, what is assumed, what is synthetic</h1>
          <p className="mt-1 text-ink-2">The dashboard mixes four kinds of information. This page separates them.</p>
        </header>
        <section>
          <h2 className="font-cond text-[18px] font-semibold">Publicly sourced facts</h2>
          <ul className="mt-2 space-y-3">
            {p.verified_facts.map((f) => (
              <li key={f.claim} className="rounded-md border border-hair bg-panel p-3">
                <p className="text-ink">{f.claim}</p>
                <p className="mt-1 text-[12.5px] text-ink-3">Status: {f.status}</p>
                <ul className="mt-1 space-y-0.5">
                  {f.sources.map((s) => (
                    <li key={s}><a href={s} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 break-all text-[12.5px] text-flow hover:underline">{s}<ExternalLink size={11} /></a></li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </section>
        <List title="Not verified, and therefore not claimed" items={p.not_verified} />
        <List title="Modelling assumptions" items={p.assumptions} />
        <List title="Synthetic elements" items={p.synthetic} />
        <List title="Responsible use" items={p.ethics} />
      </div>
    </div>
  );
}

function List({ title, items }: { title: string; items: string[] }) {
  return (
    <section>
      <h2 className="font-cond text-[18px] font-semibold">{title}</h2>
      <ul className="mt-2 list-disc space-y-1.5 pl-5 text-ink-2">{items.map((i) => <li key={i}>{i}</li>)}</ul>
    </section>
  );
}
