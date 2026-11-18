# Owner accepts the Rp 50,000 starter profile

Date: 2026-11-18. Decision record; nothing was written to any Trader instance.

The owner chose, by multiple-choice answers: the Rp 50,000 profile; limits as written (risk per trade 1.5%, daily loss Rp 1,500, drawdown 10%, one position, order cap Rp 20,000); paper costs kept as in the profile with tax (0.25) and clearing (0.05) flagged unverified (OQ-5 stays open); and asked the agent to set `"status": "accepted"` in the file.

Changed: `deploy/trader/owner-defaults.rp50000.json` (status and a `decision` block), `tests/trader/test_owner_defaults.py`, ADR-055 status line.

Not done, owner-led: loading it. From the repository root, with the owner's own email and password at the prompt: `python deploy/trader/import_owner_profile.py deploy/trader/owner-defaults.rp50000.json --email <owner email>` (dry run), then the same with `--apply` and typing APPLY. The instance stays `HALTED`, every strategy `PAPER`; no exchange is contacted.
