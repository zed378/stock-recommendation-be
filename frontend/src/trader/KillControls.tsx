import { useState } from "react";
import { useI18n } from "@/i18n/context";
import { Button, ConfirmDialog, Field, inputClass, Modal } from "@/components/primitives";
import { StepUpDialog } from "@/trader/StepUpDialog";
import { useKill, useResume, type Tier } from "@/trader/mutations";
import type { TradingState } from "@/trader/types";

/**
 * HALT from anywhere: one confirmed click, because stopping should be easy.
 *
 * Used in the state bar on every page, so it takes no props from the page's own
 * data. If everything else on the screen failed to load, this still works.
 */
export function HaltButton({ disabled }: { disabled?: boolean }) {
  const { t } = useI18n();
  const kill = useKill();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="danger" size="sm" onClick={() => setOpen(true)} disabled={disabled}>
        {t("trader.bar.halt")}
      </Button>
      {open && (
        <ConfirmDialog
          title={t("trader.btn.halt")}
          message={t("trader.confirm.halt")}
          confirmLabel={t("trader.confirm.go", { tier: "HALT" })}
          destructive
          busy={kill.isPending}
          onCancel={() => setOpen(false)}
          onConfirm={() => kill.mutate({ tier: "HALT" }, { onSettled: () => setOpen(false) })}
        />
      )}
    </>
  );
}

type Step = null | "CANCEL" | "FLATTEN" | "FLATTEN_STEPUP" | "RESUME";

/** The full set of stop controls, with the explanation each action needs. */
export function KillControls({
  state,
  openOrderCount,
}: {
  state: TradingState;
  openOrderCount: number | null;
}) {
  const { t } = useI18n();
  const kill = useKill();
  const resume = useResume();
  const [step, setStep] = useState<Step>(null);
  const [typed, setTyped] = useState("");
  const [note, setNote] = useState("");
  const close = () => {
    setStep(null);
    setTyped("");
    setNote("");
  };
  const run = (tier: Tier, stepUp?: string) =>
    kill.mutate({ tier, stepUp }, { onSettled: close });

  const halted = state !== "RUNNING";
  const rows: { tier: Tier; desc: string; action: () => void }[] = [
    { tier: "HALT", desc: t("trader.controls.halt.desc"), action: () => run("HALT") },
    { tier: "CANCEL", desc: t("trader.controls.cancel.desc"), action: () => setStep("CANCEL") },
    { tier: "FLATTEN", desc: t("trader.controls.flatten.desc"), action: () => setStep("FLATTEN") },
  ];

  return (
    <div className="space-y-4">
      <ul className="divide-y divide-line">
        {rows.map((row) => (
          <li key={row.tier} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="max-w-prose text-sm text-muted">{row.desc}</p>
            <Button
              variant="danger"
              onClick={row.action}
              disabled={kill.isPending}
              aria-label={`${t(`trader.btn.${row.tier === "HALT" ? "halt" : row.tier === "CANCEL" ? "cancel" : "flatten"}`)}: ${row.desc}`}
              className="sm:w-32"
            >
              {row.tier}
            </Button>
          </li>
        ))}
        <li className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="max-w-prose text-sm text-muted">{t("trader.controls.resume.desc")}</p>
          <Button
            variant="ghost"
            onClick={() => setStep("RESUME")}
            disabled={!halted || resume.isPending}
            className="sm:w-32"
          >
            {t("trader.btn.resume")}
          </Button>
        </li>
      </ul>

      {kill.error && (
        <p role="alert" className="text-sm text-fall">
          {kill.error.message}
        </p>
      )}

      {step === "CANCEL" && (
        <ConfirmDialog
          title={t("trader.btn.cancel")}
          message={
            openOrderCount === null
              ? t("trader.controls.cancel.desc")
              : t("trader.confirm.cancel", { count: openOrderCount })
          }
          confirmLabel={t("trader.confirm.go", { tier: "CANCEL" })}
          destructive
          busy={kill.isPending}
          onCancel={close}
          onConfirm={() => run("CANCEL")}
        />
      )}

      {step === "FLATTEN" && (
        <Modal
          title={t("trader.btn.flatten")}
          onClose={close}
          footer={
            <>
              <Button variant="ghost" onClick={close} autoFocus>
                {t("common.cancel")}
              </Button>
              <Button
                variant="danger"
                disabled={typed.trim() !== "FLATTEN"}
                onClick={() => setStep("FLATTEN_STEPUP")}
              >
                {t("trader.confirm.go", { tier: "FLATTEN" })}
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <p className="leading-relaxed">{t("trader.confirm.flatten")}</p>
            <Field label={t("trader.confirm.typeWord", { word: "FLATTEN" })}>
              <input
                className={inputClass}
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                autoComplete="off"
                spellCheck={false}
              />
            </Field>
          </div>
        </Modal>
      )}

      {step === "FLATTEN_STEPUP" && (
        <StepUpDialog scope="FLATTEN" onCancel={close} onGranted={(grant) => run("FLATTEN", grant)} />
      )}

      {step === "RESUME" && (
        <Modal
          title={t("trader.resume.title")}
          onClose={close}
          footer={
            <>
              <Button variant="ghost" onClick={close} disabled={resume.isPending}>
                {t("common.cancel")}
              </Button>
              <Button
                busy={resume.isPending}
                disabled={!note.trim()}
                onClick={() => resume.mutate({ note }, { onSuccess: close })}
              >
                {t("trader.resume.go")}
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <p className="leading-relaxed">{t("trader.controls.resume.desc")}</p>
            <Field label={t("trader.resume.note")}>
              <textarea
                className={inputClass}
                rows={3}
                autoFocus
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </Field>
            {resume.error && (
              <p role="alert" className="text-sm text-fall">
                {resume.error.message}
              </p>
            )}
          </div>
        </Modal>
      )}
    </div>
  );
}
