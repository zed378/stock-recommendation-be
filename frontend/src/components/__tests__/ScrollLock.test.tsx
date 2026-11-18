import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { I18nContext, type I18n } from "@/i18n/context";
import { locales, type MessageKey } from "@/i18n/messages";
import { lockScroll, Modal, unlockScroll } from "@/components/primitives";

const i18n: I18n = {
  locale: "en",
  setLocale: () => {},
  t: (key: MessageKey) => locales.en[key] ?? key,
  n: (v) => String(v ?? "-"),
  money: (v) => String(v ?? "-"),
  pct: (v) => String(v ?? "-"),
  date: (v) => String(v ?? "-"),
  dateTime: (v) => String(v ?? "-"),
};

beforeEach(() => {
  document.body.style.overflow = "";
});
afterEach(() => {
  cleanup();
  document.body.style.overflow = "";
});

/** A review dialog with a password dialog above it, both closed in one render, as the allowlist
 * and limits screens do after a successful save. */
function TwoDialogs() {
  const [open, setOpen] = useState(true);
  return (
    <I18nContext.Provider value={i18n}>
      <button type="button" onClick={() => setOpen(false)}>
        close both
      </button>
      {open && (
        <>
          <Modal title="Review" onClose={() => {}}>
            review
          </Modal>
          <Modal title="Password" onClose={() => {}}>
            password
          </Modal>
        </>
      )}
    </I18nContext.Provider>
  );
}

describe("page scroll lock", () => {
  it("locks while a dialog is open and unlocks when it closes", () => {
    render(
      <I18nContext.Provider value={i18n}>
        <Modal title="One" onClose={() => {}}>
          body
        </Modal>
      </I18nContext.Provider>,
    );
    expect(document.body.style.overflow).toBe("hidden");
    cleanup();
    expect(document.body.style.overflow).toBe("");
  });

  it("unlocks after two stacked dialogs close together (the stuck-page bug)", () => {
    render(<TwoDialogs />);
    expect(document.body.style.overflow).toBe("hidden");
    fireEvent.click(screen.getByText("close both"));
    expect(document.body.style.overflow).toBe("");
  });

  it("keeps the lock until the last dialog is gone, whatever the closing order", () => {
    lockScroll();
    lockScroll();
    unlockScroll();
    expect(document.body.style.overflow).toBe("hidden");
    unlockScroll();
    expect(document.body.style.overflow).toBe("");
    unlockScroll(); // an extra unlock is harmless
    expect(document.body.style.overflow).toBe("");
  });

  it("puts back whatever value the page had before the first dialog", () => {
    document.body.style.overflow = "scroll";
    lockScroll();
    unlockScroll();
    expect(document.body.style.overflow).toBe("scroll");
  });
});
