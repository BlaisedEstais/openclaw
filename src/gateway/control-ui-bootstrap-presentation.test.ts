import { describe, expect, it, onTestFinished, vi } from "vitest";
import { resolveControlUiBootstrapPresentation } from "./control-ui-bootstrap-presentation.js";

it.each([
  {
    readOnly: "1",
    nixMode: undefined,
    notice: "  Edit in Console. ",
    expected: true,
    guidance: "Edit in Console.",
  },
  { readOnly: undefined, nixMode: "1", notice: " ", expected: true, guidance: undefined },
  {
    readOnly: undefined,
    nixMode: undefined,
    notice: "Edit in Console.",
    expected: false,
    guidance: undefined,
  },
])(
  "reports the config write policy (read-only: $readOnly, Nix: $nixMode)",
  ({ readOnly, nixMode, notice, expected, guidance }) => {
    vi.stubEnv("OPENCLAW_CONFIG_READONLY", readOnly);
    vi.stubEnv("OPENCLAW_NIX_MODE", nixMode);
    vi.stubEnv("OPENCLAW_CONFIG_READONLY_NOTICE", notice);
    onTestFinished(() => vi.unstubAllEnvs());
    expect(resolveControlUiBootstrapPresentation(undefined)).toMatchObject({
      configReadOnly: expected,
      configReadOnlyNotice: guidance,
    });
  },
);

describe("Control UI model defaults bootstrap", () => {
  it.each([undefined, "configured"] as const)(
    "projects %s without model restrictions",
    (newSessionModelDefaults) => {
      const result = resolveControlUiBootstrapPresentation({
        gateway: { controlUi: { newSessionModelDefaults } },
      });
      expect(result.newSessionModelDefaults).toBe(newSessionModelDefaults ?? "last-used");
      expect(result).not.toHaveProperty("modelSelectionPolicy");
    },
  );
});

it.each([undefined, false, true])("projects composer inference opt-in: %s", (enabled) => {
  expect(
    resolveControlUiBootstrapPresentation({
      gateway: { controlUi: { experimental: { composerPredictions: { enabled } } } },
    }).composerPredictionsEnabled,
  ).toBe(enabled === true);
});

it.each([undefined, false, true])(
  "projects the bubble lab only when enabled: %s",
  (chatBubbles) => {
    expect(
      resolveControlUiBootstrapPresentation({
        gateway: { controlUi: { experimental: { chatBubbles } } },
      }).chatBubblesEnabled,
    ).toBe(chatBubbles === true);
  },
);
