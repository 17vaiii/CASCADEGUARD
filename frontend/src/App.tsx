import { FlaskConical, PanelLeftClose } from "lucide-react";
import { useEffect } from "react";
import { ScenarioLab } from "./components/ScenarioLab";
import { SidePanel } from "./components/SidePanel";
import { Timeline } from "./components/Timeline";
import { TopBar } from "./components/TopBar";
import { DemoGuide, startDemo } from "./features/demo/DemoGuide";
import { EnergyBalanceView } from "./features/energy/EnergyBalanceView";
import { EvaluationView } from "./features/evaluation/EvaluationView";
import { InvestigateView } from "./features/investigate/InvestigateView";
import { SourcesView } from "./features/sources/SourcesView";
import { NetworkCanvas } from "./features/twin/NetworkCanvas";
import { useBootstrap, useStateSync } from "./lib/controller";
import { useApp } from "./lib/store";

export default function App() {
  useBootstrap();
  useStateSync();
  const view = useApp((s) => s.view);
  const sim = useApp((s) => s.sim);
  const labOpen = useApp((s) => s.labOpen);
  const setLabOpen = useApp((s) => s.setLabOpen);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (["INPUT", "SELECT", "TEXTAREA"].includes(tag)) return;
      const s = useApp.getState();
      if (e.code === "Space") { e.preventDefault(); s.setPlaying(!s.playing); }
      if (e.code === "ArrowRight") s.step(e.shiftKey ? 24 : 1);
      if (e.code === "ArrowLeft") s.step(e.shiftKey ? -24 : -1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex h-full flex-col">
      <TopBar onStartDemo={startDemo} />
      <main className="min-h-0 flex-1">
        {!sim ? (
          <div className="flex h-full items-center justify-center text-ink-3">Starting the simulation backend…</div>
        ) : view === "twin" ? (
          <div className={`grid h-full ${labOpen ? "grid-cols-[320px_minmax(0,1fr)_380px]" : "grid-cols-[44px_minmax(0,1fr)_380px]"}`}>
            <aside className="relative min-h-0 border-r border-hair bg-panel">
              {labOpen ? (
                <>
                  <button onClick={() => setLabOpen(false)} aria-label="Collapse Scenario Lab" title="Collapse Scenario Lab"
                    className="absolute right-2 top-3 z-10 rounded p-1 text-ink-3 hover:bg-raised hover:text-ink"><PanelLeftClose size={16} /></button>
                  <ScenarioLab />
                </>
              ) : (
                <button onClick={() => setLabOpen(true)} aria-label="Open Scenario Lab"
                  className="flex h-full w-full flex-col items-center gap-3 pt-4 text-ink-2 hover:bg-raised hover:text-ink">
                  <FlaskConical size={17} color="var(--color-truth)" />
                  <span className="font-cond text-[14px] [writing-mode:vertical-rl]">Scenario Lab</span>
                </button>
              )}
            </aside>
            <section className="min-h-0 bg-plane"><NetworkCanvas /></section>
            <aside className="min-h-0 border-l border-hair bg-panel"><SidePanel /></aside>
          </div>
        ) : view === "energy" ? <EnergyBalanceView />
          : view === "investigate" ? <InvestigateView />
            : view === "evaluation" ? <EvaluationView />
              : <SourcesView />}
      </main>
      {view !== "evaluation" && view !== "sources" && <Timeline />}
      <DemoGuide />
    </div>
  );
}
