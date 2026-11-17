import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AIProvidersPanel } from "@/components/admin/AIProviders";
import { I18nContext, type I18n } from "@/i18n/context";
import { locales } from "@/i18n/messages";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() }));
vi.mock("@/api/client", () => ({
  api,
  errorMessage: (_: unknown, fallback: string) => fallback,
}));
vi.mock("@/components/toastContext", () => ({ useToast: () => ({ show: vi.fn() }) }));

const t = (key: keyof typeof locales.en, vars?: Record<string, string>) => {
  let text: string = locales.en[key] ?? key;
  for (const [k, v] of Object.entries(vars ?? {})) text = text.replace(`{${k}}`, v);
  return text;
};
const i18n: I18n = {
  locale: "en",
  setLocale: () => {},
  t: t as I18n["t"],
  n: (v) => String(v ?? "-"),
  money: (v) => String(v ?? "-"),
  pct: (v) => String(v ?? "-"),
  date: (v) => String(v ?? "-"),
  dateTime: (v) => String(v ?? "-"),
};

// The Field label wraps its hint too, so the name starts with the label rather than equalling it.
const keyLabel = new RegExp(`^${t("admin.providers.apiKey")}`);

const modelCalls = () =>
  api.POST.mock.calls.filter(([path]) => path === "/admin/ai-providers/models");

function openEditor() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nContext.Provider value={i18n}>
        <AIProvidersPanel />
      </I18nContext.Provider>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getAllByRole("button", { name: t("admin.providers.add") })[0]);
}

beforeEach(() => {
  api.GET.mockImplementation(async (path: string) =>
    path === "/providers"
      ? { data: { registered: { ai: ["openai_compatible"] } } }
      : { data: [] },
  );
  api.POST.mockImplementation(async (path: string) =>
    path === "/admin/ai-providers/models"
      ? { data: { ok: true, models: ["model-small", "model-large"], error: null } }
      : { data: {} },
  );
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("choosing a model from what the key can use", () => {
  it("asks nothing until there is a key, then fetches by itself and offers a dropdown", async () => {
    openEditor();
    const keyBox = await screen.findByLabelText(keyLabel);
    expect(screen.getByLabelText(t("admin.providers.model")).tagName).toBe("INPUT");
    expect(modelCalls()).toHaveLength(0);

    fireEvent.change(keyBox, { target: { value: "sk-typed" } });

    const dropdown = await screen.findByRole("combobox", { name: t("admin.providers.model") }, { timeout: 3000 });
    expect(modelCalls()).toHaveLength(1);
    expect(modelCalls()[0][1].body).toMatchObject({ api_key: "sk-typed" });
    expect(screen.getByRole("option", { name: "model-large" })).toBeInTheDocument();
    expect(dropdown).toHaveValue("");
    expect(screen.getByText(t("admin.providers.modelsFound", { count: "2" }))).toBeInTheDocument();
  });

  it("saves the model that was picked", async () => {
    openEditor();
    fireEvent.change(await screen.findByLabelText(keyLabel), {
      target: { value: "sk-typed" },
    });
    fireEvent.change(screen.getByPlaceholderText("primary"), { target: { value: "main" } });
    const dropdown = await screen.findByRole("combobox", { name: t("admin.providers.model") }, { timeout: 3000 });
    fireEvent.change(dropdown, { target: { value: "model-large" } });

    fireEvent.click(screen.getByRole("button", { name: t("common.save") }));

    await waitFor(() => expect(api.POST).toHaveBeenCalledWith("/admin/ai-providers", expect.anything()));
    const saved = api.POST.mock.calls.find(([path]) => path === "/admin/ai-providers");
    expect(saved?.[1].body).toMatchObject({ name: "main", default_model: "model-large", api_key: "sk-typed" });
  });

  it("falls back to typing when the key is refused, and says why", async () => {
    api.POST.mockImplementation(async (path: string) =>
      path === "/admin/ai-providers/models"
        ? { data: { ok: false, models: [], error: "ProviderUnavailableError: client error 401" } }
        : { data: {} },
    );
    openEditor();
    fireEvent.change(await screen.findByLabelText(keyLabel), {
      target: { value: "sk-wrong" },
    });

    expect(await screen.findByText(/client error 401/, undefined, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByLabelText(t("admin.providers.model")).tagName).toBe("INPUT");
  });

  it("lets a keyless local server be asked with the button", async () => {
    openEditor();
    await screen.findByLabelText(keyLabel);
    fireEvent.change(screen.getByPlaceholderText("https://api.example.com/v1"), {
      target: { value: "http://localhost:11434/v1" },
    });
    expect(modelCalls()).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: t("admin.providers.fetchModels") }));

    await screen.findByRole("combobox", { name: t("admin.providers.model") });
    expect(modelCalls()[0][1].body).toMatchObject({ base_url: "http://localhost:11434/v1" });
  });

  it("keeps a way to type a model that is not in the list", async () => {
    openEditor();
    fireEvent.change(await screen.findByLabelText(keyLabel), {
      target: { value: "sk-typed" },
    });
    const dropdown = await screen.findByRole("combobox", { name: t("admin.providers.model") }, { timeout: 3000 });

    fireEvent.change(dropdown, { target: { value: "__manual__" } });

    expect(screen.getByLabelText(t("admin.providers.model")).tagName).toBe("INPUT");
  });
});
