"""L05: two invariant checks for the C-07 dispute dialog (CONV-002).

INV-AMT  level 2 (number with tolerance): every EUR amount the agent ties to the
         disputed charge on steps 2..N equals the amount the customer gave on step 1.
INV-RC   level 1 (exact equality): every reason code the agent asserts for the case
         on steps 3..N equals the code it named first (steps 1-2).
         Codes offered as alternatives ("if ...", "whether ...", "such as ...",
         "instead") are not counted.
An amount or code that is not mentioned on a step is not a failure: the invariant
checks that a value did not change, the oracle checks that it was right.

Usage (from the repo root):
  docker compose run --rm --entrypoint python eval invariants.py --profile clean --runs 1
  docker compose run --rm --entrypoint python eval invariants.py --profile lesson-05 --runs 5
  options: --scenario 5|7|10 (default 7), --summarize-after N (default 2)
  re-grade a saved report:  ... invariants.py --recheck reports/invariants-<...>.json
Sentences that name only other transaction ids (e.g. a TX-0403 row in a list) are skipped.
"""
import argparse
import datetime as dt
import json
import pathlib
import re

import assertions as A
import stand

C07 = [
    "I'm CUS-0004. Transaction TX-0401, 240.00 EUR: the goods never arrived. "
    "Which reason code applies?",
    "Can I dispute it?",
    "What is my daily card limit?",
    "And the FX spread if I pay in USD?",
    "Fine. Back to that charge — what do I do next?",
    "240 euro, as I said at the start.",
    "And I still have time to file, right?",
]
SCENARIOS = {
    7: C07,
    5: [C07[0], C07[1], C07[2], C07[4], C07[6]],
    10: C07[:6] + [
        "Different question: what is the SEPA cut-off time for same-day transfers?",
        "And if a SWIFT transfer is returned, how long until the money is back?",
        "OK, back to the TechMart charge — which reason code are we filing under?",
        "And I still have time to file, right?",
    ],
}
CUSTOMER = "CUS-0004"

CODE_RE = re.compile(
    r"\b(fraud[_ ]card[_ ]not[_ ]present|goods[_ ]not[_ ]received|"
    r"duplicate[_ ]charge|service[_ ]not[_ ]rendered|unauthorized[_ ]debit)\b", re.I)
MONEY_RE = re.compile(
    r"(?:\bEUR|€)\s?(\d[\d,]*\d(?:\.\d+)?|\d(?:\.\d+)?)(?![\d-])"
    r"|(?<![\w\-.,])(\d[\d,]*\d(?:\.\d+)?|\d(?:\.\d+)?)\s?(?:EUR|euro)\b", re.I)
CASE_CTX_RE = re.compile(
    r"\b(charges?|purchase|transactions?|dispute|TechMart|refund|goods)\b|TX-\d", re.I)
ALTERNATIVE_RE = re.compile(r"\b(if|whether|unless|such as|instead|would)\b", re.I)
TXID_RE = re.compile(r"\bTX-\d{3,4}\b", re.I)
SENTENCE_RE = re.compile(r"(?<=[.!?])[\"”*)]*\s+|\n+")


def _code(raw: str) -> str:
    return raw.lower().replace(" ", "_")


def _sentences(text: str) -> list[str]:
    return [s for s in SENTENCE_RE.split(text or "") if s and s.strip()]


def check_dialog(turns: list[str], answers: list[str]) -> dict:
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s?EUR|EUR\s?(\d[\d,]*(?:\.\d+)?)", turns[0], re.I)
    ref_amount = float((m.group(1) or m.group(2)).replace(",", ""))
    t = TXID_RE.search(turns[0])
    ref_tx = t.group(0).upper() if t else None
    ref_code = None
    steps = []
    for i, answer in enumerate(answers, 1):
        found_codes = [_code(c) for c in CODE_RE.findall(answer or "")]
        if ref_code is None and i <= 2 and found_codes:
            ref_code = found_codes[0]
        amount_fail, code_fail = [], []
        for sen in _sentences(answer):
            ids = {x.upper() for x in TXID_RE.findall(sen)}
            if ref_tx and ids and ref_tx not in ids:
                continue  # the sentence is about another transaction
            if i > 1 and CASE_CTX_RE.search(sen):
                for g1, g2 in MONEY_RE.findall(sen):
                    value = (g1 or g2).replace(",", "")
                    v = A.level2_numeric(value, ref_amount, 0.01)
                    if not v.passed:
                        amount_fail.append({"value": float(value), "sentence": sen[:200]})
            if i > 2 and ref_code and not ALTERNATIVE_RE.search(sen):
                for raw in CODE_RE.findall(sen):
                    v = A.level1_exact(_code(raw), ref_code)
                    if not v.passed:
                        code_fail.append({"value": _code(raw), "sentence": sen[:200]})
        steps.append({"step": i, "answer": answer,
                      "inv_amount_fail": amount_fail, "inv_code_fail": code_fail})
    return {
        "ref_amount": ref_amount, "ref_code": ref_code,
        "inv_amount": {"level": 2, "passed": not any(s["inv_amount_fail"] for s in steps),
                       "failed_steps": [s["step"] for s in steps if s["inv_amount_fail"]]},
        "inv_code": {"level": 1, "passed": ref_code is not None
                     and not any(s["inv_code_fail"] for s in steps),
                     "failed_steps": [s["step"] for s in steps if s["inv_code_fail"]]},
        "steps": steps,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="lesson-05")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--scenario", type=int, choices=sorted(SCENARIOS), default=7)
    ap.add_argument("--summarize-after", type=int, default=2)
    ap.add_argument("--recheck", help="re-grade a saved invariants report, no stand calls")
    args = ap.parse_args()

    if args.recheck:
        old = json.loads(pathlib.Path(args.recheck).read_text(encoding="utf-8"))
        turns = SCENARIOS[old["scenario_steps"]]
        for r in old["runs"]:
            res = check_dialog(turns, [st["answer"] for st in r["steps"]])
            print(f"run {r['run']}: INV-AMT(L2) {'PASS' if res['inv_amount']['passed'] else 'FAIL'}"
                  f" {res['inv_amount']['failed_steps']} | INV-RC(L1) "
                  f"{'PASS' if res['inv_code']['passed'] else 'FAIL'} {res['inv_code']['failed_steps']}")
        return

    turns = SCENARIOS[args.scenario]
    runs = []
    try:
        for n in range(1, args.runs + 1):
            stand.reset()
            stand.set_profile(args.profile)
            stand.set_summarize_after(args.summarize_after)
            results = stand.dialog(turns, CUSTOMER)
            res = check_dialog(turns, [r.get("answer", "") for r in results])
            res["run"] = n
            res["request_ids"] = [r.get("request_id") for r in results]
            res["summarized_at"] = [
                i for i, r in enumerate(results, 1)
                if r.get("request_id")
                and stand.has_span(stand.trace(r["request_id"]), "agent.summarize")]
            runs.append(res)
            print(f"run {n}: INV-AMT(L2) {'PASS' if res['inv_amount']['passed'] else 'FAIL'}"
                  f" {res['inv_amount']['failed_steps']} | INV-RC(L1) "
                  f"{'PASS' if res['inv_code']['passed'] else 'FAIL'}"
                  f" {res['inv_code']['failed_steps']} | summarize at {res['summarized_at']}")
    finally:
        stand.set_summarize_after(8)

    amt_red = sum(not r["inv_amount"]["passed"] for r in runs)
    rc_red = sum(not r["inv_code"]["passed"] for r in runs)
    print(f"{args.profile}, {args.scenario} steps: INV-AMT red in {amt_red} of {len(runs)}, "
          f"INV-RC red in {rc_red} of {len(runs)}")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    out = pathlib.Path("reports") / f"invariants-{args.profile}-{args.scenario}steps-{stamp}.json"
    out.write_text(json.dumps({
        "profile": args.profile, "scenario_steps": args.scenario,
        "summarize_after": args.summarize_after, "prompt_version": stand.prompt_version(),
        "inv_amount_red": amt_red, "inv_code_red": rc_red, "runs": runs,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {out}")


if __name__ == "__main__":
    main()
