import { useState } from "react";
import { useAuth } from "@/auth/context";
import { useI18n } from "@/i18n/context";
import { Button, Field, inputClass, Modal } from "@/components/primitives";
import { idempotencyKey, traderApi, unwrap, TraderError } from "@/trader/client";

export type StepUpScope = "FLATTEN" | "PROMOTE_AUTO" | "RAISE_LIMIT" | "CREDENTIALS";

/**
 * Ask for the password again and trade it for a one-use grant (ADR-046).
 *
 * The password goes to the Trader once, which forwards it once to the analysis
 * API; it is cleared from state as soon as the call returns, on success or not.
 * The grant is single use and expires in five minutes, so it is handed straight
 * to the caller and never kept.
 */
export function StepUpDialog({
  scope,
  onGranted,
  onCancel,
}: {
  scope: StepUpScope;
  onGranted: (grant: string) => void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const { user } = useAuth();
  const [email, setEmail] = useState(user?.email ?? "");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setFailed(null);
    try {
      const out = await unwrap<{ grant: string }>(
        traderApi.POST("/trader/v1/stepup", {
          params: { header: { "Idempotency-Key": idempotencyKey() } },
          body: { email, password, scope },
        }),
      );
      onGranted(out.data.grant);
    } catch (err) {
      setFailed(err instanceof TraderError ? err.message : t("trader.stepup.failed"));
    } finally {
      setPassword("");
      setBusy(false);
    }
  };

  return (
    <Modal
      title={t("trader.stepup.title")}
      onClose={onCancel}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button onClick={submit} busy={busy} disabled={!email || !password}>
            {t("trader.stepup.submit")}
          </Button>
        </>
      }
    >
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (email && password) void submit();
        }}
      >
        <p className="leading-relaxed">{t("trader.stepup.desc")}</p>
        <Field label={t("trader.stepup.email")}>
          <input
            className={inputClass}
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        <Field label={t("trader.stepup.password")}>
          <input
            className={inputClass}
            type="password"
            autoComplete="current-password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        {failed && (
          <p role="alert" className="text-sm text-fall">
            {failed}
          </p>
        )}
      </form>
    </Modal>
  );
}
