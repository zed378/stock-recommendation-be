# Cost model: tax on sales only, numbers from the owner's account screen (ADR-060)

Owner's request: research the real fee, tax and clearing (OQ-5), then "lanjutkan usul itu" with a screenshot of their Indodax trading fee screen.

Research (2026-11-19, secondary sources plus DJP and Indodax's blog): PPh Pasal 22 final 0.21% on sales of crypto, no PPN on the trade itself (PMK 50/2025, in force 2025-08-01); the bourse (CFX) fee is 0.00555% on IDR markets since 2026-10-01. The owner's screen (IDR market, PRO) confirms it exactly: buy maker 0.10555% (service 0.1, tax 0, bourse 0.00555), buy taker 0.20555%, sell maker 0.31555% (tax 0.21), sell taker 0.41555%.

Changed: `CostModel.cost(quote_value, maker, side)` charges the fee and the bourse fee on every fill and the tax on SELL only (`paper/executor.py`; both call sites pass the side); profiles revised to tax 0.21 and clearing 0.00555 (the Rp 50,000 profile's `decision` block now cites the account screen); UI labels "Tax (sales only)" and "Bourse (clearing) fee" in both languages; ADR-060; OQ-5 answered for the IDR market in the backlog; the paper-trading spec notes the rule. Tests: three new cost tests (the four screen figures to the digit, a round trip pays the tax once, an unknown side is refused), one existing assertion updated (a buy no longer pays tax), the profile test now expects the account-screen numbers. 631 passed.

Effect: a round trip costs about 0.42% (maker) instead of about 0.80% in the model; paper and backtest results become less pessimistic by about 0.4 points per round trip. Lowering the stored costs still needs the owner's password. Not recomputed: the 18 backtest rows and the paper fills already stored (old model); the backtest is re-run after the owner applies the revised numbers with `import_owner_profile.py`.
Not covered: a different fee tier, the USDT market, and whether the 0.1% service fee already includes PPN on the commission (the screen shows one figure).
