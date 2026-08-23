"""Quick engine smoke test — not part of the pytest suite."""
import sys
sys.path.insert(0, ".")

from chain_chat.db import ChainDB
from chain_chat.golden import run_golden, all_pass
from chain_chat.canned import CannedEngine
from chain_chat.nl2sql import ask, llm_from_env

db = ChainDB("data/snapshot")
print("== schema_sql (first 800 chars) ==")
print(db.schema_sql()[:800])
print("\n== catalog summary ==")
cat = db.catalog(sample_rows=2)
print(cat[:1200])

print("\n== golden queries ==")
results = run_golden(db)
for r in results:
    print(f"  {r['id']:28s} ok={r['ok']} rows={len(r.get('rows') or [])} err={r.get('error')}")
print("all pass:", all_pass(results))

print("\n== canned answers ==")
canned = CannedEngine(db)
for q in ["Which token moved the most yesterday?",
          "How much USDC was transferred in the last 30 days?",
          "Which labeled address sent the most transfers?",
          "What is the meaning of life?"]:
    a = canned.answer(q)
    print(f"Q: {q}\n  -> {a.text}\n  sql={a.sql}\n")

print("== ask() with no key ==")
a = ask("Which token moved the most yesterday?", db, llm_from_env())
print("source:", a.source, "| text:", a.text)
db.close()