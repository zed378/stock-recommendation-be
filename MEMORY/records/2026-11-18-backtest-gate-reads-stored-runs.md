# Backtest promotion gate reads stored runs (ADR-059), and the scroll fix

Owner's answers on 2026-11-18: deploy the scroll fix, and "saya setuju berubah" to the gate change.

**Correction to what was said earlier.** I told the owner the gate read "a number the owner supplies, not the stored rows". More exactly: a typed figure took precedence, and when none was typed the gate fell back to the newest single stored run. Both were weak; ADR-059 replaces them.

Changed: `backtest/evidence.py` (`backtest_evidence`: latest run per pair for the version in force, same start equity as the newest, plain sum of returns, with pair and trade counts), `promotion/gates.py` (the backtest gate uses it and ignores `supplied.backtest_return_pct`), `api/app.py` (the promote route refuses a body that carries `backtest_return_pct`, HTTP 400 `typed_evidence_refused`). Tests: `tests/trader/test_backtest_gate.py` (6: no run means no evidence, sum of latest per pair, a typed figure changes nothing in either direction, another version has none, mixed start equities are not mixed, the API refuses a typed figure); the promotion tests now store a BACKTEST run instead of typing a figure; one assertion in `test_j4_features.py` follows the new measured text.
The frontend never sent the figure, so no screen changed; the gate's measured text now reads like `-1.246 (sum over 18 pairs, 16 trades)`.

With the 18 runs recorded earlier today the gate reads -1.246% over 18 pairs and 16 trades (checked read-only on the VM after the deploy), below the owner's 0% threshold: red, with the evidence now behind it. Not verified: the new text on the screen; the gate on the VM (not exercised, no promotion was attempted).
Also deployed in the same release: the dialog scroll-lock fix (`6613e22`, a count of open dialogs).
