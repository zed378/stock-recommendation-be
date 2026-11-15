import { useState } from "react";
import { useI18n, type MessageKey } from "@/i18n/context";
import { Button, Card, ConfirmDialog, Field, inputClass } from "@/components/primitives";
import { PanelBody } from "@/trader/components";
import { traderApi } from "@/trader/client";
import { useTraderQuery } from "@/trader/hooks";
import { useRemoveCredential, useStoreCredential, useTestCredential } from "@/trader/mutations";
import { StepUpDialog } from "@/trader/StepUpDialog";
import type { CredentialItem, CredentialKind, Credentials } from "@/trader/types";

const COPY: Record<
  CredentialKind,
  { title: MessageKey; rules: MessageKey; key: MessageKey; secret: MessageKey; remove: MessageKey }
> = {
  indodax: {
    title: "trader.cred.indodax.title",
    rules: "trader.cred.indodax.rules",
    key: "trader.cred.indodax.key",
    secret: "trader.cred.indodax.secret",
    remove: "trader.cred.removeIndodax",
  },
  telegram: {
    title: "trader.cred.telegram.title",
    rules: "trader.cred.telegram.rules",
    key: "trader.cred.telegram.key",
    secret: "trader.cred.telegram.secret",
    remove: "trader.cred.removeTelegram",
  },
};

/**
 * The exchange key and the Telegram token.
 *
 * Write-only by construction: the fields accept a value and nothing on this page
 * can display one. What comes back is the last four characters, when it was last
 * tested, and whether the master key can still decrypt it. The values are held in
 * component state only until the request is sent, then cleared whether it worked or
 * not, and they are never put in a toast, a log line, or a cache. Storing, replacing,
 * and removing ask for the password again; a key is tested read-only before it
 * replaces the old one, and a key that can withdraw is refused by the server.
 */
export function TraderCredentials() {
  const { t } = useI18n();
  const query = useTraderQuery<Credentials>(
    ["credentials"],
    () => traderApi.GET("/trader/v1/credentials"),
    { interval: false },
  );
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-lg font-semibold text-ink">{t("trader.cred.title")}</h1>
        <p className="mt-1 max-w-prose text-sm text-muted">{t("trader.cred.intro")}</p>
      </header>
      <PanelBody query={query}>
        {(data) =>
          !data.available ? (
            <Card>
              <p role="alert" className="text-sm text-fall">
                {t("trader.cred.unavailable")}
              </p>
            </Card>
          ) : (
            <div className="space-y-6">
              {data.items.map((item) => (
                <CredentialCard key={item.kind} item={item} />
              ))}
            </div>
          )
        }
      </PanelBody>
    </div>
  );
}

function CredentialCard({ item }: { item: CredentialItem }) {
  const { t, dateTime } = useI18n();
  const copy = COPY[item.kind];
  const store = useStoreCredential();
  const test = useTestCredential();
  const remove = useRemoveCredential();
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const [step, setStep] = useState<null | "store" | "remove">(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  // The values are wiped the moment they are handed to the request, not when it returns.
  const send = (grant: string) => {
    const body = { kind: item.kind, key: key.trim(), secret: secret.trim(), stepUp: grant };
    setKey("");
    setSecret("");
    setStep(null);
    void store.run(body).then((ok) => setNote(ok ? t("trader.cred.saved") : null));
  };

  const result = (ok: boolean | null | undefined) =>
    ok ? t("trader.cred.passed") : t("trader.cred.failed");

  return (
    <Card title={<h2 className="text-sm font-medium text-ink">{t(copy.title)}</h2>}>
      <div className="space-y-5">
        <p className="max-w-prose text-xs leading-relaxed text-muted">{t(copy.rules)}</p>

        <div className="space-y-1 text-sm">
          {item.configured ? (
            <>
              <p className="text-ink">{t("trader.cred.stored", { hint: item.hint ?? "" })}</p>
              <p className="text-muted">
                {item.last_test_at
                  ? t("trader.cred.lastTest", {
                      when: dateTime(item.last_test_at),
                      result: result(item.last_test_ok),
                    })
                  : t("trader.cred.neverTested")}
              </p>
              {item.readable === false && (
                <p role="alert" className="text-fall">
                  {t("trader.cred.unreadable")}
                </p>
              )}
            </>
          ) : (
            <p className="text-muted">{t("trader.cred.none")}</p>
          )}
        </div>

        <form
          className="space-y-4 border-t border-line pt-4"
          autoComplete="off"
          onSubmit={(event) => {
            event.preventDefault();
            if (key.trim() && secret.trim()) setStep("store");
          }}
        >
          <p className="text-sm font-medium text-ink">
            {item.configured ? t("trader.cred.replace") : t("trader.cred.enter")}
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t(copy.key)}>
              {/* type=password hides it on screen; autocomplete is off so a browser does not offer
                  to remember an exchange key as if it were a login. */}
              <input
                className={`${inputClass} font-mono`}
                type="password"
                autoComplete="new-password"
                spellCheck={false}
                value={key}
                onChange={(e) => setKey(e.target.value)}
              />
            </Field>
            <Field label={t(copy.secret)}>
              <input
                className={`${inputClass} font-mono`}
                type="password"
                autoComplete="new-password"
                spellCheck={false}
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
              />
            </Field>
          </div>
          <p className="max-w-prose text-xs text-muted">
            {t("trader.cred.saveHint")} {t("trader.cred.fieldsNote")}
          </p>
          <Button type="submit" busy={store.isPending} disabled={!key.trim() || !secret.trim()}>
            {t("trader.cred.save")}
          </Button>
          <div role="status" aria-live="polite" className="space-y-1">
            {store.isSuccess && note && (
              <>
                <p className="text-sm text-ink">{note}</p>
                {item.kind === "indodax" && <p className="text-xs text-watch">{t("trader.cred.revokeOld")}</p>}
              </>
            )}
            {store.error && (
              <p role="alert" className="text-sm text-fall">
                {store.error.message}
              </p>
            )}
          </div>
        </form>

        {item.configured && (
          <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
            <Button
              variant="ghost"
              busy={test.isPending}
              onClick={() => test.mutate({ kind: item.kind })}
              aria-describedby={`test-${item.kind}`}
            >
              {t("trader.cred.test")}
            </Button>
            <Button variant="danger" onClick={() => setConfirmRemove(true)} disabled={remove.isPending}>
              {t("trader.cred.remove")}
            </Button>
            <p id={`test-${item.kind}`} className="text-xs text-muted">
              {t("trader.cred.testing")}
            </p>
            <div role="status" aria-live="polite" className="w-full">
              {test.data && (
                <p className="text-sm text-ink">
                  {t("trader.cred.tested", { result: result(test.data.last_test_ok) })}
                  {test.data.reason ? ` ${test.data.reason}` : ""}
                </p>
              )}
              {test.error && <p className="text-sm text-fall">{test.error.message}</p>}
              {remove.error && <p className="text-sm text-fall">{remove.error.message}</p>}
              {remove.isSuccess && <p className="text-sm text-ink">{t("trader.cred.removed")}</p>}
            </div>
          </div>
        )}
      </div>

      {step === "store" && (
        <StepUpDialog
          scope="CREDENTIALS"
          onCancel={() => {
            // Cancelling also clears what was typed: nothing should linger in the page.
            setStep(null);
            setKey("");
            setSecret("");
          }}
          onGranted={send}
        />
      )}
      {confirmRemove && (
        <ConfirmDialog
          title={t("trader.cred.remove")}
          message={`${t("trader.cred.confirmRemove", { kind: t(copy.title) })} ${t(copy.remove)}`}
          confirmLabel={t("trader.cred.remove")}
          destructive
          onCancel={() => setConfirmRemove(false)}
          onConfirm={() => {
            setConfirmRemove(false);
            setStep("remove");
          }}
        />
      )}
      {step === "remove" && (
        <StepUpDialog
          scope="CREDENTIALS"
          onCancel={() => setStep(null)}
          onGranted={(grant) => {
            setStep(null);
            remove.mutate({ kind: item.kind, stepUp: grant });
          }}
        />
      )}
    </Card>
  );
}
